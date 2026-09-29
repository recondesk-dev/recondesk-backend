"use client";

import { Fragment, type CSSProperties, type ReactNode } from "react";
import { Inbox } from "lucide-react";
import { useTranslations } from "next-intl";

import { formatINR, formatINRNumber, formatInrCompact } from "@/lib/format";

// ─── Shared class tokens ─────────────────────────────────────────────────────

export const filterInputClass =
  "h-9 rounded-[6px] border border-[#E2E8F0] bg-white px-3.5 text-[13px] text-[#0F172A] placeholder:text-[#94A3B8] outline-none transition-colors focus:border-[#94A3B8]";

export const filterRowClass =
  "flex w-full flex-wrap items-center gap-2.5";

export const filterToolbarClass = "mb-3 space-y-2.5";

export const filterAmountInputClass = `${filterInputClass} w-[92px] shrink-0`;

export const filterDateInputClass = `${filterInputClass} w-[130px] shrink-0`;

export const filterGstinInputClass = `${filterInputClass} min-w-[150px] max-w-full flex-1`;

export const filterDropdownClass = `${filterInputClass} min-w-[120px] shrink-0 cursor-pointer text-[#475569] font-medium hover:border-[#94A3B8]`;

/** Wider pill select for “Sort by” labels like “Amount: High to Low”. */
export const filterSortDropdownClass = `${filterInputClass} min-w-[160px] shrink-0 cursor-pointer text-[#475569] font-medium hover:border-[#94A3B8]`;

export const filterToggleClass =
  "inline-flex h-9 items-center rounded-[6px] px-3 text-xs font-semibold transition-colors duration-150";

export const filterToggleActiveClass =
  "bg-[#0F172A] text-white";

export const filterToggleIdleClass =
  "border border-[#E2E8F0] bg-[#F8FAFC] text-[#64748B] hover:border-[#BFDBFE] hover:bg-[#EFF6FF] hover:text-[#2563EB]";

export const csvDownloadBtnClass =
  "inline-flex h-8 shrink-0 items-center justify-center gap-1.5 rounded-[6px] border border-[#E2E8F0] bg-white px-3 text-xs font-semibold text-[#475569] transition-colors duration-150 hover:bg-[#F8FAFC] disabled:cursor-not-allowed disabled:opacity-50";

export const sectionContainerClass =
  "box-border w-full max-w-full bg-white p-6";

export const pageContentClass =
  "box-border w-full max-w-full space-y-3.5";

/** Default grid for secondary panels (GSTR-3B, etc.) */
export const statCardsGridClass =
  "mt-4 grid w-full min-w-0 grid-cols-2 gap-3 border-t border-[#F0F0F0] pt-4 lg:grid-cols-3";

/** Results summary: secondary metrics + dominant money cards */
export const resultsSummaryGridClass =
  "mt-5 grid w-full min-w-0 grid-cols-2 gap-4 sm:grid-cols-3 lg:grid-cols-5";

export const statCardValueClass =
  "text-[2rem] font-bold tabular-nums tracking-tight";

export const tableWrapClass = "w-full min-w-0 max-w-full overflow-x-auto";

export const tableClass = "w-full table-auto border-collapse text-left";

export const decisionTableWrapClass = tableWrapClass;

export const decisionTableClass =
  "w-full min-w-[800px] table-auto border-collapse text-left";

export const tableHeadClass =
  "text-[11px] font-bold uppercase tracking-[0.5px] text-[#64748B]";

export const tableHeadCellClass =
  "px-4 py-3 text-left bg-[#FAFAFA] border-b border-[#F1F5F9] font-bold text-[11px] uppercase tracking-[0.5px] text-[#64748B] whitespace-nowrap";

export const tableRowClass =
  "border-b border-[#F8FAFC] bg-white transition-colors duration-100 last:border-b-0 hover:bg-[#F8FAFC]";

export const tableCellClass = "px-4 py-3.5 align-middle text-[13px] text-[#334155]";

export const tableTruncateCellClass =
  `${tableCellClass} overflow-hidden text-ellipsis whitespace-nowrap`;

export const tableStickyCheckboxHeadClass =
  "sticky left-0 z-10 w-8 bg-[#FAFAFA] border-b border-[#F1F5F9] px-3 py-2";

export const tableStickyCheckboxCellClass =
  "sticky left-0 z-10 w-8 bg-white px-3 py-2 transition-colors duration-100 group-hover:bg-[#F8FAFC]";

export const topSuppliersTableClass = "w-full table-auto border-collapse text-left";

export const topSuppliersThGstin = `${tableHeadCellClass} pl-6 w-[18%]`;
export const topSuppliersTdGstin = `${tableCellClass} pl-6 max-w-0 overflow-visible font-mono text-xs sm:text-[13px] font-semibold text-[#0F172A] tracking-[0.2px]`;
export const topSuppliersThTradeName = `${tableHeadCellClass} w-[32%]`;
export const topSuppliersTdTradeName = `${tableCellClass} max-w-0 overflow-visible text-[13px] font-medium text-[#334155]`;
export const topSuppliersThInvoiceCount = `${tableHeadCellClass} w-[14%] text-center`;
export const topSuppliersTdInvoiceCount = `${tableCellClass} text-center text-[13px] font-semibold text-[#334155] tabular-nums`;
export const topSuppliersThTotal = `${tableHeadCellClass} w-[22%] text-right`;
export const topSuppliersTdTotal = `${tableCellClass} text-right text-[13px] font-bold text-[#0F172A]`;
export const topSuppliersThImpact = `${tableHeadCellClass} pr-6 w-[14%] text-right`;
export const topSuppliersTdImpact = `${tableCellClass} pr-6 text-right text-[13px] font-semibold`;

export const matchedTableClass =
  "w-full min-w-[800px] table-auto border-collapse text-left";

export const matchedThGstin = `${tableHeadCellClass} pl-6 min-w-[140px] whitespace-nowrap`;
export const matchedTdGstin = `${tableCellClass} pl-6 font-mono text-xs sm:text-[13px] font-semibold text-[#0F172A] tracking-[0.2px]`;
export const matchedThInvoice = `${tableHeadCellClass} min-w-[110px] whitespace-nowrap`;
export const matchedTdInvoice = `${tableCellClass} font-mono text-xs sm:text-[13px] font-bold text-[#1D4ED8]`;
export const matchedThDate = `${tableHeadCellClass} min-w-[100px] whitespace-nowrap`;
export const matchedTdDate = `${tableCellClass} whitespace-nowrap text-xs sm:text-[13px] text-[#64748B]`;
export const matchedThAmount = `${tableHeadCellClass} min-w-[100px] whitespace-nowrap text-right`;
export const matchedTdAmount = `${tableCellClass} whitespace-nowrap text-right text-[13px] font-bold text-[#0F172A]`;
export const matchedThMatchLevel = `${tableHeadCellClass} min-w-[120px] whitespace-nowrap`;
export const matchedTdMatchLevel = `${tableCellClass}`;
export const matchedThConfidence = `${tableHeadCellClass} min-w-[110px] whitespace-nowrap`;
export const matchedTdConfidence = `${tableCellClass} whitespace-nowrap`;
export const matchedThDiscrepancy = `${tableHeadCellClass} min-w-[100px] whitespace-nowrap text-right`;
export const matchedTdDiscrepancy = `${tableCellClass} text-[13px] text-right font-semibold`;
export const matchedThGuidanceWhat = `${tableHeadCellClass} min-w-[160px] whitespace-nowrap`;
export const matchedTdGuidanceWhat = `${tableCellClass} text-[13px] text-[#334155]`;
export const matchedThGuidanceWhy = `${tableHeadCellClass} min-w-[140px] whitespace-nowrap`;
export const matchedTdGuidanceWhy = `${tableCellClass} text-xs italic text-gray-500`;
export const matchedThGuidanceNext = `${tableHeadCellClass} min-w-[140px] whitespace-nowrap`;
export const matchedTdGuidanceNext = `${tableCellClass} text-xs sm:text-[13px] font-medium text-[var(--ink)]`;
export const matchedThNotes = `${tableHeadCellClass} pr-6 min-w-[80px] whitespace-nowrap text-right`;
export const matchedTdNotes = `${tableCellClass} pr-6 whitespace-nowrap text-right text-xs text-gray-400`;
export const matchedThIms = `${tableHeadCellClass} min-w-[90px] whitespace-nowrap`;
export const matchedTdIms = `${tableCellClass} whitespace-nowrap`;

export type ImsStatusValue =
  | "accepted"
  | "rejected"
  | "pending"
  | "no_action_taken"
  | string;

export function ImsStatusBadge({ status }: { status?: string | null }) {
  const raw = (status || "no_action_taken").trim().toLowerCase();
  const label =
    raw === "accepted"
      ? "Accepted"
      : raw === "rejected"
        ? "Rejected"
        : raw === "pending"
          ? "Pending"
          : "No action";
  const tone =
    raw === "accepted"
      ? "bg-[#DCFCE7] text-[#166534]"
      : raw === "rejected"
        ? "bg-[#FEF2F2] text-[#991B1B]"
        : raw === "pending"
          ? "bg-[#FFFBEB] text-[#92400E]"
          : "bg-[#F1F5F9] text-[#64748B]";
  return (
    <span
      className={`inline-flex items-center rounded px-1.5 py-0.5 text-[10px] font-medium ${tone}`}
    >
      {label}
    </span>
  );
}

export function DecisionTableColGroup({
  includeNotice = false,
  includeIms = false,
}: {
  includeNotice?: boolean;
  includeIms?: boolean;
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
      <col style={{ width: includeNotice || includeIms ? "12%" : "15%" }} />
      <col style={{ width: includeNotice || includeIms ? "11%" : "14%" }} />
      <col style={{ width: includeNotice || includeIms ? "10%" : "13%" }} />
      <col style={{ width: includeNotice || includeIms ? "7%" : "8%" }} />
      {includeIms ? <col style={{ width: "9%" }} /> : null}
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
  numberColorClass = "text-[var(--ink)]",
  numberStyle,
}: {
  amount: number;
  sizeClass?: string;
  numberColorClass?: string;
  numberStyle?: CSSProperties;
}) {
  return (
    <span className={`inline-flex tabular-nums ${sizeClass}`}>
      <span
        className={`text-gray-400 ${sizeClass}`}
        style={{ fontFamily: "Arial, system-ui, -apple-system, sans-serif", fontWeight: "inherit" }}
      >
        ₹
      </span>
      <span className={numberColorClass} style={numberStyle}>
        {formatINRNumber(amount)}
      </span>
    </span>
  );
}

export function AmountDisplay({ amount }: { amount: number }) {
  return <InrAmount amount={amount} />;
}

/**
 * Money for tight cards: abbreviate large values (₹1.35Cr) so they never
 * truncate; full en-IN amount is always available via title/hover.
 */
export function CompactStatAmount({
  amount,
  sizeClass = statCardValueClass,
  className = "",
}: {
  amount: number;
  sizeClass?: string;
  emphasize?: boolean;
  className?: string;
}) {
  const full = formatINR(amount);
  const abs = Math.abs(amount);
  const useCompact = abs >= 1e5;
  const display = useCompact ? formatInrCompact(amount) : full;

  const isNeg = display.startsWith("-");
  const core = isNeg ? display.slice(1) : display;
  const hasRupee = core.startsWith("₹");
  const formattedNumber = hasRupee ? core.slice(1) : core;

  return (
    <span
      className={`inline-block whitespace-nowrap tabular-nums ${sizeClass} ${className}`}
      title={full}
    >
      {isNeg ? "-" : ""}
      {hasRupee ? (
        <span style={{ fontFamily: "Arial, system-ui, -apple-system, sans-serif", fontWeight: "inherit" }}>
          ₹
        </span>
      ) : null}
      {formattedNumber}
    </span>
  );
}

export function EmptyTableState({
  title,
  description,
  action,
}: {
  title: string;
  description?: string;
  action?: ReactNode;
}) {
  return (
    <div className="flex flex-col items-center justify-center rounded-[1.25rem] bg-[#F7F7F8] px-6 py-14 text-center">
      <div className="mb-3 flex h-10 w-10 items-center justify-center rounded-full bg-white shadow-sm">
        <Inbox className="h-4 w-4 text-gray-400" aria-hidden />
      </div>
      <p className="text-[13px] font-medium text-[var(--ink)]">{title}</p>
      {description ? (
        <p className="mt-1 max-w-sm text-[12px] leading-relaxed text-gray-500">
          {description}
        </p>
      ) : null}
      {action ? <div className="mt-4">{action}</div> : null}
    </div>
  );
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

type StatEmphasis = "default" | "secondary" | "attention" | "danger";

const statAccentMeta: Record<
  StatAccent,
  { numberColor: string }
> = {
  neutral: { numberColor: "#1a1a1a" },
  matched: { numberColor: "#16a34a" },
  missed: { numberColor: "#e53935" },
  risk: { numberColor: "#e53935" },
  saved: { numberColor: "#1a1a1a" },
  reversed: { numberColor: "#e53935" },
  pending: { numberColor: "#1a1a1a" },
  review_required: { numberColor: "#ea580c" },
  linked: { numberColor: "#1a1a1a" },
};

export function StatCard({
  label,
  value,
  accent = "neutral",
  subtext,
  extraContent,
  emphasis = "default",
  title: titleAttr,
}: {
  label: string;
  value: ReactNode;
  accent?: StatAccent;
  subtext?: string;
  extraContent?: ReactNode;
  /** Visual weight: danger/attention get larger type; secondary is quieter. */
  emphasis?: StatEmphasis;
  title?: string;
}) {
  const colors = statAccentMeta[accent];
  const isDanger = emphasis === "danger";
  const resolvedEmphasis: StatEmphasis =
    emphasis !== "default"
      ? emphasis
      : accent === "saved" || accent === "reversed" || accent === "pending"
        ? "attention"
        : "default";
  const isSecondary = resolvedEmphasis === "secondary";

  return (
    <div
      className={`box-border flex min-w-0 w-full flex-col gap-1.5 rounded-[10px] border border-[#E2E8F0] bg-white p-4 sm:p-5 transition-shadow duration-200 hover:shadow-md ${
        isSecondary ? "opacity-90" : ""
      }`}
      style={{
        minHeight: 100,
        boxShadow: "0 2px 8px rgba(0, 0, 0, 0.04)",
      }}
      title={titleAttr}
    >
      <p
        className="min-w-0 whitespace-normal text-[0.8rem] font-medium text-[#6b7280]"
      >
        {label}
      </p>
      <div
        className={`min-w-0 overflow-visible whitespace-nowrap ${statCardValueClass}`}
        style={{ color: colors.numberColor }}
      >
        {typeof value === "string" && value.includes("₹") ? (
          <>
            {value.split("₹").map((part, idx) => (
              <Fragment key={idx}>
                {idx > 0 && (
                  <span
                    style={{
                      fontFamily: "Arial, system-ui, -apple-system, sans-serif",
                      fontWeight: "inherit",
                    }}
                  >
                    ₹
                  </span>
                )}
                {part}
              </Fragment>
            ))}
          </>
        ) : (
          value
        )}
      </div>
      {subtext && (
        <p
          className="truncate text-[0.75rem] leading-snug text-[#9ca3af]"
          title={subtext}
        >
          {subtext}
        </p>
      )}
      {extraContent}
    </div>
  );
}

type SectionAmountBadgeVariant = "claim" | "risk" | "rule37" | "neutral";

const sectionAmountBadgeStyles: Record<
  SectionAmountBadgeVariant,
  { card: string; label: string; amount: string }
> = {
  claim: {
    card: "bg-[#F8FAFC] border border-[#E2E8F0]",
    label: "text-[#94A3B8]",
    amount: "text-[#0F172A]",
  },
  risk: {
    card: "bg-[#FFF7F7] border border-[#FECACA]",
    label: "text-[#991B1B]",
    amount: "text-[#DC2626]",
  },
  rule37: {
    card: "bg-[#FFFBEB] border border-[#FDE68A]",
    label: "text-[#92400E]",
    amount: "text-[#D97706]",
  },
  neutral: {
    card: "bg-[#F8FAFC] border border-[#E2E8F0]",
    label: "text-[#94A3B8]",
    amount: "text-[#0F172A]",
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
      className={`inline-flex min-w-[100px] flex-col items-center justify-center rounded-[8px] px-3.5 py-1.5 ${styles.card}`}
    >
      <span
        className={`text-center text-[9px] font-semibold uppercase tracking-[0.4px] ${styles.label}`}
      >
        {label}
      </span>
      <span title={formatINR(amount)}>
        <InrAmount
          amount={amount}
          sizeClass="whitespace-nowrap text-sm font-bold tracking-tight"
          numberColorClass={styles.amount}
        />
      </span>
      {sublabel ? (
        <span className="text-center text-[9px] text-[#94A3B8]">
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
      <div className="flex min-w-0 items-center gap-2.5">
        <span
          className="h-1.5 w-1.5 shrink-0 rounded-full"
          style={{ backgroundColor: dotColor }}
          aria-hidden
        />
        <h2 className="min-w-0 truncate text-[15px] font-semibold tracking-tight text-[var(--ink)]">
          {title}
        </h2>
      </div>
      {showRight && (
        <div className="flex shrink-0 flex-col items-end gap-2 sm:flex-row sm:items-center">
          {resolvedBadges.length > 0 ? (
            <div className="flex flex-wrap items-stretch justify-end gap-2.5">
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
    high: "bg-[#FEF2F2] text-[#EF4444]",
    medium: "bg-[#F0F0F0] text-gray-700",
    low: "bg-[#F0F0F0] text-gray-500",
  }[level];
  const label = level === "medium" ? "Medium" : level === "high" ? "High" : "Low";
  return (
    <span
      className={`inline-flex rounded-full px-2.5 py-0.5 text-[11px] font-medium ${cls}`}
    >
      {label}
    </span>
  );
}

export type DecisionStatus = "pending" | "acted" | "ignored";

export function DecisionStatusPill({ status }: { status: DecisionStatus }) {
  if (status === "acted")
    return (
      <span className="inline-flex rounded-full bg-[var(--ink)] px-2.5 py-0.5 text-[11px] font-medium text-white">
        Done
      </span>
    );
  if (status === "ignored")
    return (
      <span className="inline-flex rounded-full bg-[#F0F0F0] px-2.5 py-0.5 text-[11px] font-medium text-gray-400 line-through">
        Ignored
      </span>
    );
  return (
    <span className="inline-flex rounded-full bg-[#F0F0F0] px-2.5 py-0.5 text-[11px] font-medium text-gray-500">
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
  | "itc_on_hold"
  | "review_required"
  | "duplicate_entry"
  | "unmatched_notes"
  | "risk"
  | "itc"
  | "rule37"
  | "section17"
  | "rcm"
  | "gstr3b"
  | "followup"
  | "ims"
  | "einvoice"
  /** Sales / GSTR-1 reconciliation buckets */
  | "unmatched_sr"
  | "unmatched_gstr1"
  | "tie_out"
  | "documents_issued"
  | "diagnostics";

const RESULTS_BUCKET_TABS: { id: ResultsBucketTabId; label: string }[] = [
  { id: "matched", label: "Matched" },
  { id: "itc_on_hold", label: "ITC On Hold" },
  { id: "review_required", label: "Review Required" },
  { id: "duplicate_entry", label: "Duplicate Entries" },
  { id: "unmatched_notes", label: "Notes — Not Auto-Matched" },
  { id: "risk", label: "ITC at Risk — Not in GSTR-2B" },
  { id: "itc", label: "Missed ITC" },
  { id: "rule37", label: "ITC at Risk — Rule 37 (Unpaid 180+ Days)" },
  { id: "section17", label: "Section 17(5)" },
  { id: "rcm", label: "RCM Reconciliation" },
  { id: "gstr3b", label: "GSTR-3B" },
  { id: "einvoice", label: "E-Invoice Check" },
  { id: "followup", label: "Follow-up Log" },
  { id: "ims", label: "IMS Actions" },
];

/** IDs treated as primary (first row) tabs on purchase pages */
const PRIMARY_TAB_IDS = new Set<ResultsBucketTabId>([
  "matched",
  "itc_on_hold",
  "review_required",
  "itc",
  "risk",
]);

/** Default purchase-side tabs. Sales pages pass an explicit `tabs` list. */
export const PURCHASE_RESULTS_BUCKET_TABS = RESULTS_BUCKET_TABS;

export const SALES_RESULTS_BUCKET_TABS: { id: ResultsBucketTabId; label: string }[] = [
  { id: "matched", label: "Matched" },
  { id: "review_required", label: "Review Required" },
  { id: "unmatched_sr", label: "Missing in GSTR-1" },
  { id: "unmatched_gstr1", label: "Extra in GSTR-1" },
  { id: "tie_out", label: "GSTR-1 vs 3B" },
  { id: "documents_issued", label: "Table 13 Docs" },
  { id: "diagnostics", label: "Diagnostics" },
];


import {
  getTable4GateBadgeInfo,
  type Table4GateBadgeInfo,
} from "@/lib/table4GateBadge";
export { getTable4GateBadgeInfo, type Table4GateBadgeInfo };

export function ResultsBucketTabs({
  active,
  onChange,
  rightContent,
  tabCounts,
  tabs,
  isRunFinalized,
  ariaLabel = "Reconciliation results",
}: {
  active: ResultsBucketTabId;
  onChange: (tab: ResultsBucketTabId) => void;
  rightContent?: ReactNode;
  /** Optional record count to display next to each tab label, e.g. { matched: 4222, review_required: 860 } */
  tabCounts?: Partial<Record<ResultsBucketTabId, number>>;
  /**
   * Override the tab list. Defaults to purchase reconciliation tabs.
   * Sales / GSTR-1 pages should pass `SALES_RESULTS_BUCKET_TABS`.
   */
  tabs?: { id: ResultsBucketTabId; label: string }[];
  isRunFinalized?: boolean;
  ariaLabel?: string;
}) {
  const isCustomTabs = tabs != null;

  if (isCustomTabs) {
    return (
      <div className="border-b border-[#F1F5F9] bg-white px-2">
        <nav className="flex flex-wrap gap-1" role="tablist" aria-label={ariaLabel}>
          {tabs.map(({ id, label }) => {
            const isActive = active === id;
            const count = tabCounts?.[id];
            return (
              <button
                key={id}
                type="button"
                role="tab"
                aria-selected={isActive}
                onClick={() => onChange(id)}
                className={`flex items-center gap-1.5 border-b-2 px-3.5 py-2.5 text-[13px] font-medium transition-colors whitespace-nowrap ${
                  isActive
                    ? "border-[#2563EB] text-[#0F172A] font-semibold"
                    : "border-transparent text-[#94A3B8] hover:text-[#0F172A]"
                }`}
              >
                <span>{label}</span>
                {count != null && (
                  <span className="rounded-full bg-[#F1F5F9] px-1.5 py-0.5 text-[10px] font-semibold text-[#475569]">
                    {count.toLocaleString("en-IN")}
                  </span>
                )}
              </button>
            );
          })}
        </nav>
      </div>
    );
  }

  const primaryBadgeStyle: Record<string, string> = {
    matched: "bg-[#DCFCE7] text-[#166534]",
    itc_on_hold: "bg-[#FEF3C7] text-[#92400E]",
    review_required: "bg-[#FFFBEB] text-[#92400E]",
    risk: "bg-[#FEF2F2] text-[#991B1B]",
    itc: "bg-[#FEF2F2] text-[#991B1B]",
    duplicate_entry: "bg-[#F1F5F9] text-[#475569]",
  };

  const tResults = useTranslations("results");

  return (
    <div className="border-b border-[#F1F5F9] bg-white">
      {/* Primary tabs */}
      <div className="flex items-center border-b border-[#F1F5F9] px-4 overflow-x-auto">
        <button
          type="button"
          role="tab"
          aria-selected={active === "matched"}
          onClick={() => onChange("matched")}
          className={`flex items-center gap-2 border-b-2 px-4 py-3 text-sm font-medium transition-colors whitespace-nowrap outline-none focus:outline-none select-none ${
            active === "matched"
              ? "border-[#2563EB] text-[#0F172A] font-bold"
              : "border-transparent text-[#64748B] hover:text-[#0F172A]"
          }`}
        >
          {tabCounts?.itc_on_hold != null && tabCounts.itc_on_hold > 0
            ? "Matched (Eligible)"
            : tResults("matched")}
          {tabCounts?.matched != null && (
            <span className={`rounded-full px-2 py-0.5 text-[11px] font-bold ${primaryBadgeStyle.matched}`}>
              {tabCounts.matched.toLocaleString("en-IN")}
            </span>
          )}
        </button>

        <button
          type="button"
          role="tab"
          aria-selected={active === "itc_on_hold"}
          onClick={() => onChange("itc_on_hold")}
          className={`flex items-center gap-2 border-b-2 px-4 py-3 text-sm font-medium transition-colors whitespace-nowrap outline-none focus:outline-none select-none ${
            active === "itc_on_hold"
              ? "border-[#D97706] text-[#0F172A] font-bold"
              : "border-transparent text-[#64748B] hover:text-[#0F172A]"
          }`}
        >
          ITC On Hold
          {tabCounts?.itc_on_hold != null && (
            <span className={`rounded-full px-2 py-0.5 text-[11px] font-bold ${primaryBadgeStyle.itc_on_hold}`}>
              {tabCounts.itc_on_hold.toLocaleString("en-IN")}
            </span>
          )}
        </button>

        <button
          type="button"
          role="tab"
          aria-selected={active === "review_required"}
          onClick={() => onChange("review_required")}
          className={`flex items-center gap-2 border-b-2 px-4 py-3 text-sm font-medium transition-colors whitespace-nowrap outline-none focus:outline-none select-none ${
            active === "review_required"
              ? "border-[#2563EB] text-[#0F172A] font-bold"
              : "border-transparent text-[#64748B] hover:text-[#0F172A]"
          }`}
        >
          {tResults("reviewRequired")}
          {tabCounts?.review_required != null && (
            <span className={`rounded-full px-2 py-0.5 text-[11px] font-bold ${primaryBadgeStyle.review_required}`}>
              {tabCounts.review_required.toLocaleString("en-IN")}
            </span>
          )}
        </button>

        <button
          type="button"
          role="tab"
          aria-selected={active === "risk"}
          onClick={() => onChange("risk")}
          className={`flex items-center gap-2 border-b-2 px-4 py-3 text-sm font-medium transition-colors whitespace-nowrap outline-none focus:outline-none select-none ${
            active === "risk"
              ? "border-[#2563EB] text-[#0F172A] font-bold"
              : "border-transparent text-[#64748B] hover:text-[#0F172A]"
          }`}
        >
          {tResults("itcAtRiskShort")}
          {tabCounts?.risk != null && (
            <span className={`rounded-full px-2 py-0.5 text-[11px] font-bold ${primaryBadgeStyle.risk}`}>
              {tabCounts.risk.toLocaleString("en-IN")}
            </span>
          )}
        </button>

        <button
          type="button"
          role="tab"
          aria-selected={active === "itc"}
          onClick={() => onChange("itc")}
          className={`flex items-center gap-2 border-b-2 px-4 py-3 text-sm font-medium transition-colors whitespace-nowrap outline-none focus:outline-none select-none ${
            active === "itc"
              ? "border-[#2563EB] text-[#0F172A] font-bold"
              : "border-transparent text-[#64748B] hover:text-[#0F172A]"
          }`}
        >
          {tResults("missedItc")}
          {tabCounts?.itc != null && (
            <span className={`rounded-full px-2 py-0.5 text-[11px] font-bold ${primaryBadgeStyle.itc}`}>
              {tabCounts.itc.toLocaleString("en-IN")}
            </span>
          )}
        </button>

        <div className="flex-1 min-w-4" />

        <button
          type="button"
          role="tab"
          aria-selected={active === "duplicate_entry"}
          onClick={() => onChange("duplicate_entry")}
          className={`flex items-center gap-2 border-b-2 px-4 py-3 text-xs sm:text-[13px] font-medium transition-colors whitespace-nowrap outline-none focus:outline-none select-none ${
            active === "duplicate_entry"
              ? "border-[#2563EB] text-[#0F172A] font-bold"
              : "border-transparent text-[#64748B] hover:text-[#0F172A]"
          }`}
        >
          {tResults("duplicateEntries")}
          {tabCounts?.duplicate_entry != null && (
            <span className={`rounded-full px-2 py-0.5 text-[11px] font-bold ${primaryBadgeStyle.duplicate_entry}`}>
              {tabCounts.duplicate_entry.toLocaleString("en-IN")}
            </span>
          )}
        </button>
      </div>

      {/* Secondary module tabs */}
      <div className="flex flex-wrap items-center gap-2 border-b border-[#F8FAFC] px-6 py-3">
        <span className="flex items-center px-1 text-[11px] font-bold uppercase tracking-wider text-[#94A3B8]">
          {tResults("modules")} →
        </span>

        <button
          type="button"
          onClick={() => onChange("rule37")}
          className={`cursor-pointer rounded-[6px] border px-3 py-1.5 text-xs font-semibold whitespace-nowrap transition-all ${
            active === "rule37"
              ? "border-[#BFDBFE] bg-[#EFF6FF] text-[#2563EB]"
              : "border-[#E2E8F0] bg-[#F8FAFC] text-[#64748B] hover:border-[#BFDBFE] hover:bg-[#EFF6FF] hover:text-[#2563EB]"
          }`}
        >
          {tResults("rule37")} <span className="ml-1 text-[11px] font-medium text-[#94A3B8]">{tResults("rule37Sub")}</span>
        </button>

        <button
          type="button"
          onClick={() => onChange("section17")}
          className={`cursor-pointer rounded-[6px] border px-3 py-1.5 text-xs font-semibold whitespace-nowrap transition-all ${
            active === "section17"
              ? "border-[#BFDBFE] bg-[#EFF6FF] text-[#2563EB]"
              : "border-[#E2E8F0] bg-[#F8FAFC] text-[#64748B] hover:border-[#BFDBFE] hover:bg-[#EFF6FF] hover:text-[#2563EB]"
          }`}
        >
          {tResults("section17_5")}
          {tabCounts?.section17 != null && (
            <span className="ml-1 text-[11px] font-bold text-[#64748B]">({tabCounts.section17})</span>
          )}
        </button>

        <button
          type="button"
          onClick={() => onChange("rcm")}
          className={`cursor-pointer rounded-[6px] border px-3 py-1.5 text-xs font-semibold whitespace-nowrap transition-all ${
            active === "rcm"
              ? "border-[#BFDBFE] bg-[#EFF6FF] text-[#2563EB]"
              : "border-[#E2E8F0] bg-[#F8FAFC] text-[#64748B] hover:border-[#BFDBFE] hover:bg-[#EFF6FF] hover:text-[#2563EB]"
          }`}
        >
          {tResults("rcm")}
        </button>

        {(() => {
          const gateInfo = getTable4GateBadgeInfo(tabCounts?.gstr3b, isRunFinalized);
          return (
            <button
              type="button"
              onClick={() => onChange("gstr3b")}
              className={`cursor-pointer rounded-[6px] border px-3 py-1.5 text-xs font-semibold whitespace-nowrap transition-all inline-flex items-center gap-1.5 ${
                active === "gstr3b"
                  ? "border-[#2563EB] bg-[#EFF6FF] text-[#2563EB] ring-1 ring-[#2563EB]/20 shadow-xs"
                  : "border-blue-200 bg-blue-50/50 text-[#1D4ED8] hover:border-[#2563EB] hover:bg-[#EFF6FF]"
              }`}
            >
              <span className={`h-1.5 w-1.5 rounded-full ${gateInfo.dotClass}`} />
              <span>{tResults("gstr3bTieOut")}</span>
              {gateInfo.badgeText && gateInfo.badgeClass && (
                <span className={`ml-1 rounded-full px-1.5 py-0.5 text-[10px] font-bold ${gateInfo.badgeClass}`}>
                  {gateInfo.badgeText}
                </span>
              )}
            </button>
          );
        })()}

        <button
          type="button"
          onClick={() => onChange("einvoice")}
          className={`cursor-pointer rounded-[6px] border px-3 py-1.5 text-xs font-semibold whitespace-nowrap transition-all ${
            active === "einvoice"
              ? "border-[#BFDBFE] bg-[#EFF6FF] text-[#2563EB]"
              : "border-[#E2E8F0] bg-[#F8FAFC] text-[#64748B] hover:border-[#BFDBFE] hover:bg-[#EFF6FF] hover:text-[#2563EB]"
          }`}
        >
          {tResults("einvoiceCheck")}
          {tabCounts?.einvoice != null && (
            <span className="ml-1 text-[11px] font-bold text-[#64748B]">({tabCounts.einvoice})</span>
          )}
        </button>

        <button
          type="button"
          onClick={() => onChange("ims")}
          className={`cursor-pointer rounded-[6px] border px-3 py-1.5 text-xs font-semibold whitespace-nowrap transition-all ${
            active === "ims"
              ? "border-[#BFDBFE] bg-[#EFF6FF] text-[#2563EB]"
              : "border-[#E2E8F0] bg-[#F8FAFC] text-[#64748B] hover:border-[#BFDBFE] hover:bg-[#EFF6FF] hover:text-[#2563EB]"
          }`}
        >
          {tResults("imsActions")}
        </button>

        <button
          type="button"
          onClick={() => onChange("followup")}
          className={`cursor-pointer rounded-[6px] border px-3 py-1.5 text-xs font-semibold whitespace-nowrap transition-all ${
            active === "followup"
              ? "border-[#BFDBFE] bg-[#EFF6FF] text-[#2563EB]"
              : "border-[#E2E8F0] bg-[#F8FAFC] text-[#64748B] hover:border-[#BFDBFE] hover:bg-[#EFF6FF] hover:text-[#2563EB]"
          }`}
        >
          {tResults("followupLog")}
        </button>

        <button
          type="button"
          onClick={() => onChange("unmatched_notes")}
          className={`cursor-pointer rounded-[6px] border px-3 py-1.5 text-xs font-semibold whitespace-nowrap transition-all ${
            active === "unmatched_notes"
              ? "border-[#BFDBFE] bg-[#EFF6FF] text-[#2563EB]"
              : "border-[#E2E8F0] bg-[#F8FAFC] text-[#64748B] hover:border-[#BFDBFE] hover:bg-[#EFF6FF] hover:text-[#2563EB]"
          }`}
        >
          {tResults("notes")}{" "}
          <span className="ml-1 text-[11px] font-bold text-[#64748B]">
            ({tabCounts?.unmatched_notes ?? 0})
          </span>
        </button>
      </div>
    </div>
  );
}
