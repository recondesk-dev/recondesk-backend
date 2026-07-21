"use client";

import type { CSSProperties, ReactNode } from "react";
import { Inbox } from "lucide-react";

import { formatINR, formatINRNumber, formatInrCompact } from "@/lib/format";

// ─── Shared class tokens ─────────────────────────────────────────────────────

export const filterInputClass =
  "h-9 rounded-full border-0 bg-[#F5F5F6] px-4 text-[13px] font-medium text-gray-700 placeholder:text-gray-400 outline-none transition-shadow focus:ring-2 focus:ring-black/10";

export const filterRowClass =
  "flex w-full flex-wrap items-center gap-2";

export const filterToolbarClass = "mb-5 space-y-2.5";

export const filterAmountInputClass = `${filterInputClass} w-[96px] shrink-0`;

export const filterDateInputClass = `${filterInputClass} w-[138px] shrink-0`;

export const filterGstinInputClass = `${filterInputClass} min-w-[140px] max-w-full flex-1`;

export const filterDropdownClass = `${filterInputClass} w-[148px] shrink-0 appearance-none`;

/** Wider pill select for “Sort by” labels like “Amount: High to Low”. */
export const filterSortDropdownClass = `${filterInputClass} w-[200px] shrink-0 appearance-none`;

export const filterToggleClass =
  "inline-flex h-9 items-center rounded-full px-3.5 text-[13px] font-medium transition-colors duration-150";

export const filterToggleActiveClass =
  "bg-[var(--ink)] text-white";

export const filterToggleIdleClass =
  "bg-[#F5F5F6] text-gray-600 hover:bg-gray-200/70";

export const csvDownloadBtnClass =
  "inline-flex h-9 shrink-0 items-center justify-center gap-2 rounded-full bg-[#F5F5F6] px-4 text-[13px] font-semibold text-gray-700 transition-colors duration-150 hover:bg-gray-200/70 disabled:cursor-not-allowed disabled:opacity-50";

export const sectionContainerClass =
  "mb-6 box-border w-full max-w-full rounded-[1.5rem] bg-white p-6 shadow-[var(--shadow-soft)]";

export const pageContentClass =
  "box-border w-full max-w-full space-y-5 overflow-x-hidden px-8 pt-5 pb-32";

/** Default grid for secondary panels (GSTR-3B, etc.) */
export const statCardsGridClass =
  "mt-4 grid w-full min-w-0 grid-cols-2 gap-3 border-t border-[#F0F0F0] pt-4 lg:grid-cols-3";

/** Results summary: secondary metrics + dominant money cards */
export const resultsSummaryGridClass =
  "mt-5 grid w-full min-w-0 grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-5";

export const statCardValueClass = "text-xl font-semibold tabular-nums tracking-tight";

export const tableWrapClass = "w-full min-w-0 overflow-x-auto rounded-[1.25rem] ring-1 ring-[#F0F0F0]";

export const tableClass = "w-full table-auto border-collapse text-left";

export const decisionTableWrapClass = tableWrapClass;

export const decisionTableClass =
  "w-full min-w-[1100px] table-auto border-collapse text-left";

export const tableHeadClass =
  "text-[11px] font-medium uppercase tracking-widest text-gray-400";

export const tableHeadCellClass =
  "px-4 py-3.5 text-left overflow-hidden text-ellipsis whitespace-nowrap";

export const tableRowClass =
  "border-b border-[#F0F0F0] bg-white transition-colors duration-100 last:border-b-0 hover:bg-[#F7F7F8]";

export const tableCellClass = "px-4 py-3 align-middle";

export const tableTruncateCellClass =
  `${tableCellClass} overflow-hidden text-ellipsis whitespace-nowrap`;

export const tableStickyCheckboxHeadClass =
  "sticky left-0 z-10 w-8 bg-white px-3 py-3.5";

export const tableStickyCheckboxCellClass =
  "sticky left-0 z-10 w-8 bg-white px-3 py-3 transition-colors duration-100 group-hover:bg-[#F7F7F8]";

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

export const matchedTableClass =
  "w-full min-w-[1080px] table-auto border-collapse text-left";

export const matchedThGstin = `${tableHeadCellClass} min-w-[150px] whitespace-nowrap`;
export const matchedTdGstin = `${tableCellClass} font-mono text-[12px] text-gray-500`;
export const matchedThInvoice = `${tableHeadCellClass} min-w-[110px] whitespace-nowrap`;
export const matchedTdInvoice = `${tableCellClass}`;
export const matchedThDate = `${tableHeadCellClass} min-w-[110px] whitespace-nowrap`;
export const matchedTdDate = `${tableCellClass} whitespace-nowrap text-[13px] text-gray-500`;
export const matchedThAmount = `${tableHeadCellClass} min-w-[100px] whitespace-nowrap text-right`;
export const matchedTdAmount = `${tableCellClass} whitespace-nowrap text-right`;
export const matchedThMatchLevel = `${tableHeadCellClass} min-w-[180px] whitespace-nowrap`;
export const matchedTdMatchLevel = `${tableCellClass}`;
export const matchedThConfidence = `${tableHeadCellClass} min-w-[100px] whitespace-nowrap text-center`;
export const matchedTdConfidence = `${tableCellClass} whitespace-nowrap text-center text-[13px] text-gray-600`;
export const matchedThDiscrepancy = `${tableHeadCellClass} min-w-[140px] whitespace-nowrap`;
export const matchedTdDiscrepancy = `${tableCellClass} text-[13px] text-gray-600`;
export const matchedThGuidanceWhat = `${tableHeadCellClass} min-w-[160px] whitespace-nowrap`;
export const matchedTdGuidanceWhat = `${tableCellClass} text-[13px] text-gray-600`;
export const matchedThGuidanceWhy = `${tableHeadCellClass} min-w-[140px] whitespace-nowrap`;
export const matchedTdGuidanceWhy = `${tableCellClass} text-[13px] italic text-gray-400`;
export const matchedThGuidanceNext = `${tableHeadCellClass} min-w-[140px] whitespace-nowrap`;
export const matchedTdGuidanceNext = `${tableCellClass} text-[13px] font-medium text-[var(--ink)]`;
export const matchedThNotes = `${tableHeadCellClass} min-w-[80px] whitespace-nowrap`;
export const matchedTdNotes = `${tableCellClass} whitespace-nowrap`;
export const matchedThIms = `${tableHeadCellClass} min-w-[100px] whitespace-nowrap text-center`;
export const matchedTdIms = `${tableCellClass} whitespace-nowrap text-center`;

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
      ? "bg-[var(--ink)] text-white"
      : raw === "rejected"
        ? "bg-[#FEF2F2] text-[#EF4444]"
        : raw === "pending"
          ? "bg-[#F0F0F0] text-gray-600"
          : "bg-[#F0F0F0] text-gray-500";
  return (
    <span
      className={`inline-flex items-center rounded-full px-2.5 py-0.5 text-[11px] font-medium ${tone}`}
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

/**
 * Money for tight cards: abbreviate large values (₹1.35Cr) so they never
 * truncate; full en-IN amount is always available via title/hover.
 */
export function CompactStatAmount({
  amount,
  emphasize = false,
  className = "",
}: {
  amount: number;
  emphasize?: boolean;
  className?: string;
}) {
  const full = formatINR(amount);
  const abs = Math.abs(amount);
  const useCompact = abs >= 1e5;
  const display = useCompact ? formatInrCompact(amount) : full;
  const size = emphasize
    ? "text-[clamp(1.125rem,2.1vw,1.625rem)] font-semibold tracking-tight"
    : "text-[clamp(1rem,1.6vw,1.25rem)] font-semibold tracking-tight";

  return (
    <span
      className={`inline-block whitespace-nowrap tabular-nums ${size} ${className}`}
      title={full}
    >
      {display}
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
  { value: string; dot: string; surface?: string }
> = {
  neutral: { value: "text-[var(--ink)]", dot: "bg-gray-300" },
  matched: { value: "text-[var(--ink)]", dot: "bg-[var(--ink)]" },
  missed: {
    value: "text-red-700",
    dot: "bg-red-500",
    surface: "bg-[#FFFBFB]",
  },
  risk: {
    value: "text-amber-800",
    dot: "bg-amber-500",
    surface: "bg-[#FFFCFA]",
  },
  saved: {
    value: "text-[var(--ink)]",
    dot: "bg-[var(--ink)]",
  },
  reversed: {
    value: "text-red-600",
    dot: "bg-red-500",
    surface: "bg-[#FFFBFB]",
  },
  pending: {
    value: "text-gray-700",
    dot: "bg-gray-400",
  },
  review_required: {
    value: "text-[var(--ink)]",
    dot: "bg-amber-500",
  },
  linked: {
    value: "text-[var(--ink)]",
    dot: "bg-gray-400",
  },
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
  // Auto-elevate saved/reversed/pending when callers omit emphasis (Rule 37, etc.)
  const resolvedEmphasis: StatEmphasis =
    emphasis !== "default"
      ? emphasis
      : accent === "saved" || accent === "reversed" || accent === "pending"
        ? "attention"
        : "default";
  const isSecondary = resolvedEmphasis === "secondary";
  const isEmphasized = isDanger || accent === "matched";

  return (
    <div
      className={`box-border flex min-w-0 w-full flex-col rounded-[1.25rem] px-4 py-4 shadow-[var(--shadow-soft)] transition-transform duration-200 hover:-translate-y-0.5 ${
        isEmphasized
          ? `${colors.surface ?? "bg-white"} gap-2.5`
          : "gap-1.5 bg-white"
      } ${isSecondary ? "opacity-90" : ""}`}
      title={titleAttr}
    >
      <div className="flex min-w-0 items-center gap-1.5">
        <span
          className={`h-1.5 w-1.5 shrink-0 rounded-full ${colors.dot}`}
          aria-hidden
        />
        <p className="min-w-0 truncate text-[10px] font-medium uppercase tracking-[0.08em] text-gray-500">
          {label}
        </p>
      </div>
      <div
        className={`min-w-0 overflow-visible whitespace-nowrap ${
          typeof value === "string" || typeof value === "number"
            ? `${isDanger ? "text-[clamp(1.125rem,2.1vw,1.625rem)]" : isSecondary ? "text-lg" : "text-xl"} font-semibold tabular-nums tracking-tight ${colors.value}`
            : ""
        }`}
      >
        {value}
      </div>
      {subtext && (
        <p
          className="truncate text-[11px] leading-snug text-gray-400"
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
    card: "bg-[#F7F7F8]",
    label: "text-gray-500",
    amount: "text-[var(--ink)]",
  },
  risk: {
    card: "bg-[#FFFBFB]",
    label: "text-red-500",
    amount: "text-red-700",
  },
  rule37: {
    card: "bg-[#FFFCFA]",
    label: "text-amber-600",
    amount: "text-amber-800",
  },
  neutral: {
    card: "bg-[#F7F7F8]",
    label: "text-gray-500",
    amount: "text-[var(--ink)]",
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
      className={`inline-flex min-w-[120px] flex-col items-center justify-center rounded-2xl px-4 py-2.5 ${styles.card}`}
    >
      <span
        className={`text-center text-[10px] font-semibold uppercase tracking-widest ${styles.label}`}
      >
        {label}
      </span>
      <span title={formatINR(amount)}>
        <InrAmount
          amount={amount}
          sizeClass="whitespace-nowrap text-lg font-semibold tracking-tight"
          numberColorClass={styles.amount}
        />
      </span>
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
  | "review_required"
  | "duplicate_entry"
  | "unmatched_notes"
  | "risk"
  | "itc"
  | "rule37"
  | "section17"
  | "gstr3b"
  | "followup"
  /** Sales / GSTR-1 reconciliation buckets */
  | "unmatched_sr"
  | "unmatched_gstr1"
  | "tie_out"
  | "documents_issued"
  | "diagnostics";

const RESULTS_BUCKET_TABS: { id: ResultsBucketTabId; label: string }[] = [
  { id: "matched", label: "Matched" },
  { id: "review_required", label: "Review Required" },
  { id: "duplicate_entry", label: "Duplicate Entries" },
  { id: "unmatched_notes", label: "Notes — Not Matched" },
  { id: "risk", label: "ITC at Risk" },
  { id: "itc", label: "Missed ITC" },
  { id: "rule37", label: "Rule 37" },
  { id: "section17", label: "Section 17(5)" },
  { id: "gstr3b", label: "GSTR-3B" },
  { id: "followup", label: "Follow-up Log" },
];

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

export function ResultsBucketTabs({
  active,
  onChange,
  rightContent,
  tabCounts,
  tabs,
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
  ariaLabel?: string;
}) {
  const tabList = tabs ?? RESULTS_BUCKET_TABS;
  return (
    <div className="mb-6 flex flex-col gap-3 sm:flex-row sm:items-end sm:justify-between">
      <nav
        className="flex flex-wrap gap-1.5"
        role="tablist"
        aria-label={ariaLabel}
      >
        {tabList.map(({ id, label }) => {
          const isActive = active === id;
          const count = tabCounts?.[id];
          return (
            <button
              key={id}
              type="button"
              role="tab"
              aria-selected={isActive}
              className={
                isActive
                  ? "inline-flex items-center gap-1.5 rounded-full bg-[var(--ink)] px-3.5 py-2 text-[13px] font-semibold text-white shadow-sm"
                  : "inline-flex items-center gap-1.5 rounded-full bg-white px-3.5 py-2 text-[13px] font-medium text-gray-500 shadow-[var(--shadow-soft)] transition-colors hover:text-[var(--ink)]"
              }
              onClick={() => onChange(id)}
            >
              <span>{label}</span>
              {count != null ? (
                <span
                  className={
                    isActive
                      ? "inline-flex min-w-[1.25rem] items-center justify-center rounded-full bg-white/15 px-1.5 py-0.5 text-[11px] font-semibold tabular-nums text-white"
                      : "inline-flex min-w-[1.25rem] items-center justify-center rounded-full bg-[#F0F0F0] px-1.5 py-0.5 text-[11px] font-medium tabular-nums text-gray-500"
                  }
                >
                  {count.toLocaleString("en-IN")}
                </span>
              ) : null}
            </button>
          );
        })}
      </nav>
      {rightContent && <div className="shrink-0">{rightContent}</div>}
    </div>
  );
}
