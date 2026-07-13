"use client";

import type { CSSProperties, ReactNode } from "react";
import { Inbox } from "lucide-react";

import { formatINR, formatINRNumber, formatInrCompact } from "@/lib/format";

// ─── Shared class tokens ─────────────────────────────────────────────────────

export const filterInputClass =
  "h-9 border border-[#E8E8EC] rounded-lg text-[13px] px-3 bg-white text-gray-800 placeholder:text-gray-400 focus:ring-2 focus:ring-brand/15 focus:border-brand outline-none transition-colors duration-150";

export const filterRowClass =
  "flex w-full flex-wrap items-center gap-2";

export const filterToolbarClass = "mb-5 space-y-2.5";

export const filterAmountInputClass = `${filterInputClass} w-[96px] shrink-0`;

export const filterDateInputClass = `${filterInputClass} w-[138px] shrink-0`;

export const filterGstinInputClass = `${filterInputClass} min-w-[140px] max-w-full flex-1`;

export const filterDropdownClass = `${filterInputClass} w-[148px] shrink-0`;

export const filterToggleClass =
  "inline-flex h-9 items-center rounded-lg border px-3 text-[13px] font-medium transition-colors duration-150";

export const filterToggleActiveClass =
  "border-brand/40 bg-brand/[0.06] text-brand";

export const filterToggleIdleClass =
  "border-[#E8E8EC] bg-white text-gray-600 hover:bg-gray-50 hover:border-gray-300";

export const csvDownloadBtnClass =
  "inline-flex h-9 shrink-0 items-center justify-center gap-2 border border-[#E8E8EC] bg-white text-gray-600 text-[13px] font-medium rounded-lg px-3.5 hover:bg-gray-50 transition-colors duration-150 disabled:cursor-not-allowed disabled:opacity-50";

export const sectionContainerClass =
  "mb-6 box-border w-full max-w-full rounded-xl border border-[#EFEFF2] bg-white p-6";

export const pageContentClass =
  "box-border w-full max-w-full space-y-5 overflow-x-hidden px-8 pt-5 pb-32";

/** Default grid for secondary panels (GSTR-3B, etc.) */
export const statCardsGridClass =
  "mt-4 grid w-full min-w-0 grid-cols-2 gap-3 border-t border-[#EFEFF2] pt-4 lg:grid-cols-3";

/** Results summary: secondary metrics + dominant money cards */
export const resultsSummaryGridClass =
  "mt-5 grid w-full min-w-0 grid-cols-2 gap-3 border-t border-[#EFEFF2] pt-5 sm:grid-cols-3 lg:grid-cols-5";

export const statCardValueClass = "text-xl font-semibold tabular-nums tracking-tight";

export const tableWrapClass = "w-full min-w-0 overflow-x-hidden";

export const tableClass = "w-full table-auto border-collapse text-left";

export const decisionTableWrapClass = tableWrapClass;

export const decisionTableClass =
  "w-full table-fixed border-collapse text-left";

export const tableHeadClass =
  "bg-[#FAFAFB] text-[11px] font-semibold uppercase tracking-wider text-gray-400";

export const tableHeadCellClass =
  "px-4 py-2.5 text-left overflow-hidden text-ellipsis whitespace-nowrap";

export const tableRowClass =
  "border-b border-[#F4F4F6] bg-white hover:bg-[#FAFAFB] transition-colors duration-100";

export const tableCellClass = "px-4 py-2.5 align-middle";

export const tableTruncateCellClass =
  `${tableCellClass} overflow-hidden text-ellipsis whitespace-nowrap`;

export const tableStickyCheckboxHeadClass =
  "sticky left-0 z-10 w-8 bg-[#FAFAFB] px-3 py-2.5";

export const tableStickyCheckboxCellClass =
  "sticky left-0 z-10 w-8 bg-white px-3 py-2.5 transition-colors duration-100 group-hover:bg-[#FAFAFB]";

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
export const matchedThDiscrepancy = `${tableHeadCellClass} w-[16%]`;
export const matchedTdDiscrepancy = `${tableCellClass} max-w-0 overflow-visible text-[13px] text-gray-600`;
export const matchedThGuidanceWhat = `${tableHeadCellClass} w-[14%]`;
export const matchedTdGuidanceWhat = `${tableCellClass} max-w-0 overflow-visible text-[13px] text-gray-600`;
export const matchedThGuidanceWhy = `${tableHeadCellClass} w-[12%]`;
export const matchedTdGuidanceWhy = `${tableCellClass} max-w-0 overflow-visible text-[13px] italic text-gray-400`;
export const matchedThGuidanceNext = `${tableHeadCellClass} w-[12%]`;
export const matchedTdGuidanceNext = `${tableCellClass} max-w-0 overflow-visible text-[13px] font-medium text-brand`;
export const matchedThNotes = `${tableHeadCellClass} w-[8%]`;
export const matchedTdNotes = `${tableCellClass}`;
export const matchedThIms = `${tableHeadCellClass} w-[10%] text-center`;
export const matchedTdIms = `${tableCellClass} text-center`;

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
      ? "bg-emerald-50 text-emerald-700 ring-emerald-200"
      : raw === "rejected"
        ? "bg-red-50 text-red-700 ring-red-200"
        : raw === "pending"
          ? "bg-amber-50 text-amber-800 ring-amber-200"
          : "bg-gray-50 text-gray-600 ring-gray-200";
  return (
    <span
      className={`inline-flex items-center rounded-md px-1.5 py-0.5 text-[11px] font-medium ring-1 ring-inset ${tone}`}
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
    <div className="flex flex-col items-center justify-center rounded-xl border border-dashed border-[#E8E8EC] bg-[#FAFAFB] px-6 py-14 text-center">
      <div className="mb-3 flex h-10 w-10 items-center justify-center rounded-full bg-white border border-[#EFEFF2]">
        <Inbox className="h-4 w-4 text-gray-400" aria-hidden />
      </div>
      <p className="text-[13px] font-medium text-gray-800">{title}</p>
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
  { value: string; dot: string; attentionBorder?: string }
> = {
  neutral: { value: "text-gray-900", dot: "bg-gray-300" },
  matched: { value: "text-gray-900", dot: "bg-brand" },
  missed: {
    value: "text-red-700",
    dot: "bg-red-500",
    attentionBorder: "border-l-red-500",
  },
  risk: {
    value: "text-amber-800",
    dot: "bg-amber-500",
    attentionBorder: "border-l-amber-500",
  },
  saved: {
    value: "text-green-700",
    dot: "bg-green-500",
    attentionBorder: "border-l-green-500",
  },
  reversed: {
    value: "text-red-600",
    dot: "bg-red-500",
    attentionBorder: "border-l-red-500",
  },
  pending: {
    value: "text-amber-700",
    dot: "bg-amber-500",
    attentionBorder: "border-l-amber-500",
  },
  review_required: {
    value: "text-amber-800",
    dot: "bg-amber-500",
    attentionBorder: "border-l-amber-500",
  },
  linked: {
    value: "text-gray-800",
    dot: "bg-violet-400",
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
  /** Visual weight: danger/attention get left accent + larger type; secondary is quieter. */
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
  const isAttention =
    resolvedEmphasis === "attention" ||
    resolvedEmphasis === "danger" ||
    isDanger;
  const isSecondary = resolvedEmphasis === "secondary";

  const cardSurface = isDanger
    ? "border-[#F0E4E4] bg-[#FFFBFB]"
    : "border-[#EFEFF2] bg-white";

  const leftAccent =
    isAttention && colors.attentionBorder
      ? `border-l-[3px] ${colors.attentionBorder}`
      : "border-l border-l-transparent";

  return (
    <div
      className={`box-border flex min-w-0 w-full flex-col rounded-xl border py-3.5 px-3.5 ${cardSurface} ${leftAccent} ${
        isDanger ? "gap-2.5 sm:col-span-1" : "gap-1.5"
      } ${isSecondary ? "opacity-90" : ""}`}
      title={titleAttr}
    >
      <div className="flex min-w-0 items-center gap-1.5">
        <span
          className={`h-1.5 w-1.5 shrink-0 rounded-full ${colors.dot}`}
          aria-hidden
        />
        <p
          className={`min-w-0 truncate font-medium uppercase tracking-[0.08em] text-gray-500 ${
            isDanger ? "text-[10px]" : "text-[10px]"
          }`}
        >
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
          className={`truncate text-[11px] leading-snug ${
            isSecondary ? "text-gray-400" : "text-gray-400"
          }`}
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
    card: "bg-green-50/80 border-green-100",
    label: "text-green-600",
    amount: "text-green-800",
  },
  risk: {
    card: "bg-red-50/80 border-red-100",
    label: "text-red-500",
    amount: "text-red-700",
  },
  rule37: {
    card: "bg-amber-50/80 border-amber-100",
    label: "text-amber-600",
    amount: "text-amber-800",
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
      className={`inline-flex min-w-[120px] flex-col items-center justify-center rounded-xl border px-4 py-2.5 ${styles.card}`}
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
        <h2 className="min-w-0 truncate text-[15px] font-semibold tracking-tight text-gray-900">
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
    high: "bg-red-50 text-red-600",
    medium: "bg-amber-50 text-amber-700",
    low: "bg-gray-100 text-gray-500",
  }[level];
  const label = level === "medium" ? "Medium" : level === "high" ? "High" : "Low";
  return (
    <span
      className={`inline-flex rounded-md px-2 py-0.5 text-[11px] font-medium ${cls}`}
    >
      {label}
    </span>
  );
}

export type DecisionStatus = "pending" | "acted" | "ignored";

export function DecisionStatusPill({ status }: { status: DecisionStatus }) {
  if (status === "acted")
    return (
      <span className="inline-flex rounded-md bg-green-50 px-2 py-0.5 text-[11px] font-medium text-green-700">
        Done
      </span>
    );
  if (status === "ignored")
    return (
      <span className="inline-flex rounded-md bg-gray-100 px-2 py-0.5 text-[11px] font-medium text-gray-400 line-through">
        Ignored
      </span>
    );
  return (
    <span className="inline-flex rounded-md bg-gray-100 px-2 py-0.5 text-[11px] font-medium text-gray-500">
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
  | "risk"
  | "itc"
  | "rule37"
  | "gstr3b"
  | "followup";

const RESULTS_BUCKET_TABS: { id: ResultsBucketTabId; label: string }[] = [
  { id: "matched", label: "Matched" },
  { id: "review_required", label: "Review Required" },
  { id: "duplicate_entry", label: "Duplicate Entries" },
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
  tabCounts,
}: {
  active: ResultsBucketTabId;
  onChange: (tab: ResultsBucketTabId) => void;
  rightContent?: ReactNode;
  /** Optional record count to display next to each tab label, e.g. { matched: 4222, review_required: 860 } */
  tabCounts?: Partial<Record<ResultsBucketTabId, number>>;
}) {
  return (
    <div className="mb-6 flex flex-col gap-3 border-b border-[#EFEFF2] sm:flex-row sm:items-end sm:justify-between">
      <nav
        className="flex flex-wrap gap-x-0.5 gap-y-0"
        role="tablist"
        aria-label="Reconciliation results"
      >
        {RESULTS_BUCKET_TABS.map(({ id, label }) => {
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
                  ? "-mb-px inline-flex items-center gap-1.5 border-b-2 border-brand px-3 py-2.5 text-[13px] font-medium text-gray-900"
                  : "inline-flex items-center gap-1.5 border-b-2 border-transparent px-3 py-2.5 text-[13px] font-medium text-gray-500 transition-colors hover:text-gray-800"
              }
              onClick={() => onChange(id)}
            >
              <span>{label}</span>
              {count != null ? (
                <span
                  className={
                    isActive
                      ? "inline-flex min-w-[1.25rem] items-center justify-center rounded-md bg-brand/10 px-1.5 py-0.5 text-[11px] font-semibold tabular-nums text-brand"
                      : "inline-flex min-w-[1.25rem] items-center justify-center rounded-md bg-gray-100 px-1.5 py-0.5 text-[11px] font-medium tabular-nums text-gray-500"
                  }
                >
                  {count.toLocaleString("en-IN")}
                </span>
              ) : null}
            </button>
          );
        })}
      </nav>
      {rightContent && <div className="mb-2 shrink-0">{rightContent}</div>}
    </div>
  );
}
