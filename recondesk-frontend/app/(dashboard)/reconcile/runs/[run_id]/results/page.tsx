"use client";

import { Check, ChevronDown, FileSpreadsheet, FileText, Info, Loader2, Shield, Trash2, Upload, X } from "lucide-react";
import { useLocale, useTranslations } from "next-intl";
import { localizeDiscrepancyReason } from "@/lib/decision-translations";
import {
  Rule37MarkPaidModal,
  type Rule37MarkPaidTarget,
} from "@/components/reconcile/Rule37MarkPaidModal";
import { ReconcilePaginationFooter } from "@/components/reconcile/ReconcilePaginationFooter";
import { AuditObservationsPanel } from "@/components/AuditObservationsPanel";
import { RcmReconciliationPanel } from "@/components/reconcile/RcmReconciliationPanel";
import { ImsActionPanel } from "@/components/reconcile/ImsActionPanel";
import { Rule37SummarySection } from "@/components/reconcile/Rule37SummarySection";
import {
  formatRule37EmptyStateMessage,
  formatRule37HeaderCoverageSublabel,
  type Rule37SummaryResponse,
} from "@/lib/rule37Summary";
import { SupplierFollowupAuditLogPanel } from "@/components/reconcile/SupplierFollowupAuditLogPanel";
import { Gstr3bSummaryView } from "@/components/reconcile/Gstr3bSummaryView";
import { EInvoiceCheckPanel } from "@/components/reconcile/EInvoiceCheckPanel";
import { AdvancedExportPanel } from "@/components/reconcile/AdvancedExportPanel";
import { SupplierFollowupLetterModal } from "@/components/reconcile/SupplierFollowupLetterModal";
import { SupplierGroupView } from "@/components/reconcile/SupplierGroupView";
import { ItcIneligibleBadge } from "@/components/reconcile/ItcIneligibleBadge";
import {
  DecisionInvoiceCard,
  DecisionInvoiceList,
} from "@/components/reconcile/DecisionInvoiceCard";
import { GstinCell } from "@/components/ui/GstinCell";
import { HoverTextCell } from "@/components/ui/HoverTextCell";
import Link from "next/link";
import { useParams, useRouter } from "next/navigation";
import {
  Fragment,
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
  type MouseEvent,
} from "react";
import useSWR, { mutate as swrMutate } from "swr";
import {
  AmountDisplay,
  CompactStatAmount,
  csvDownloadBtnClass,
  DecisionTableColGroup,
  decisionTableClass,
  decisionTableWrapClass,
  decisionTd,
  decisionTh,
  DecisionStatusPill,
  EmptyTableState,
  filterAmountInputClass,
  filterDateInputClass,
  filterDropdownClass,
  filterSortDropdownClass,
  filterGstinInputClass,
  filterInputClass,
  filterRowClass,
  filterToggleActiveClass,
  filterToggleClass,
  filterToggleIdleClass,
  filterToolbarClass,
  InrAmount,
  ImpactBadge,
  matchedTableClass,
  matchedTdAmount,
  matchedTdConfidence,
  matchedTdDate,
  matchedTdDiscrepancy,
  matchedTdGuidanceNext,
  matchedTdGuidanceWhat,
  matchedTdGuidanceWhy,
  matchedTdGstin,
  matchedTdInvoice,
  matchedTdMatchLevel,
  matchedTdNotes,
  matchedThAmount,
  matchedThConfidence,
  matchedThDate,
  matchedThDiscrepancy,
  matchedThGuidanceNext,
  matchedThGuidanceWhat,
  matchedThGuidanceWhy,
  matchedThGstin,
  matchedThInvoice,
  matchedThMatchLevel,
  matchedThNotes,
  matchedThIms,
  matchedTdIms,
  ImsStatusBadge,
  pageContentClass,
  ResultsBucketTabs,
  rule37BorderClass,
  type ResultsBucketTabId,
  Rule37SeverityLabel,
  sectionContainerClass,
  SectionAmountBadge,
  SectionHeader,
  resultsSummaryGridClass,
  StatCard,
  tableCellClass,
  tableHeadCellClass,
  tableHeadClass,
  tableRowClass,
  tableStickyCheckboxCellClass,
  tableStickyCheckboxHeadClass,
  tableWrapClass,
  topSuppliersTableClass,
  topSuppliersTdGstin,
  topSuppliersTdImpact,
  topSuppliersTdInvoiceCount,
  topSuppliersTdTotal,
  topSuppliersTdTradeName,
  topSuppliersThGstin,
  topSuppliersThImpact,
  topSuppliersThInvoiceCount,
  topSuppliersThTotal,
  topSuppliersThTradeName,
} from "@/components/reconcile/ResultsUi";
import { apiFetch, isApiError, reconcileSettingsApi, tallyBridgeApi } from "@/lib/api";
import {
  AUTH_PROFILE_SWR_OPTIONS,
  authProfileFetcher,
} from "@/lib/auth-profile";
import {
  fetchAllBucketPages,
  groupRowsBySupplier,
} from "@/lib/groupBySupplier";
import { fetchReconciliationReportData } from "@/lib/reconciliationReportData";
import {
  buildReconciliationReportPdf,
  reportPdfFilename,
} from "@/lib/reconciliationReportPdf";
import { downloadBlobAsFile } from "@/lib/download";
import {
  isValidReconcileTablePageSize,
  persistReconcileTablePageSize,
  readStoredReconcileTablePageSize,
  RECONCILE_PAGE_SIZE_STORAGE_KEYS,
  RECONCILE_TABLE_PAGE_SIZE_OPTIONS,
} from "@/lib/reconcileTablePageSize";
import {
  formatINR,
  formatInrCompact,
  formatTaxDifferenceDisplay,
} from "@/lib/format";
import { useAccessToken } from "@/lib/hooks/useAccessToken";

const DEFAULT_AUTO_APPROVE_THRESHOLD = 95;

const API_URL = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

function formatPeriod(period: string): string {
  if (!period) return "";
  const parts = period.split("-");
  if (parts.length !== 2) return period;
  const [year, month] = parts;
  const y = parseInt(year, 10);
  const m = parseInt(month, 10);
  if (isNaN(y) || isNaN(m)) return period;
  const date = new Date(y, m - 1);
  return isNaN(date.getTime())
    ? period
    : date.toLocaleString("en-IN", { month: "long", year: "numeric" });
}

// ─── Types ─────────────────────────────────────────────────────────────────

type MatchLevel = "EXACT" | "FUZZY" | "MANUAL" | "UNMATCHED";
type DecisionStatus = "pending" | "acted" | "ignored";
type DecisionType = "claim" | "follow_up" | "escalate" | "ignore" | null;
type Rule37Urgency = "CRITICAL" | "HIGH" | "MEDIUM";
type Rule37ActionStatus = "resolved" | "acknowledged" | "pending_review" | "rejected";

type Rule37ReviewMetadata = {
  reason?: string;
  bill_ref?: string;
  party?: string;
  supplier_name?: string;
  invoice_number?: string;
  record_id?: string;
  run_id?: string;
  bill_ref_score?: number;
  party_sim?: number;
  party_gate_min?: number;
  amount_paid?: number;
  payment_date?: string;
};

type ComparedField = {
  field_name: string;
  match_type: "exact" | "fuzzy" | "not_matched" | string;
  field_score: number | null;
};

type ReconcileRow = {
  id: string;
  supplier_gstin: string;
  trade_name?: string | null;
  invoice_number: string;
  invoice_date: string;
  amount: number;
  match_level: MatchLevel;
  confidence_score: number;
  discrepancy_note: string | null;
  discrepancy_reason?: string | null;
  tax_difference_paise?: number | null;
  decision_what: string | null;
  decision_why: string | null;
  decision_next: string | null;
  decision_rule?: string | null;
  decision_confidence?: string | null;
  decision_matched_fields?: string[] | null;
  decision_differed_fields?: string[] | null;
  decision_normalized_pairs?: [string, string][] | null;
  decision_status: DecisionStatus;
  decision_type: DecisionType;
  notes_count: number;
  gstr2b_data: Record<string, string | number>;
  purchase_register_data: Record<string, string | number>;
  rule37_urgency?: Rule37Urgency;
  rule37_action_status?: Rule37ActionStatus | null;
  rule37_action_id?: string | null;
  rule37_review_metadata?: Rule37ReviewMetadata | null;
  invoice_amount?: number;
  rule37_payment_coverage?: "full" | "partial" | "pending_review" | null;
  section_17_5_category?: string;
  match_confidence?: number | null;
  compared_fields?: ComparedField[] | null;
  ims_status?: string | null;
  /** Set when confidence-threshold auto-triage promoted this row from Review Required. */
  auto_approved?: boolean;
  itc_available?: boolean;
  itc_reason?: string | null;
};

/** Small pill showing L5/fuzzy invoice-similarity score. Only renders when match_confidence is present. */
function MatchConfidenceBadge({
  score,
  onClick,
}: {
  score: number;
  onClick?: (e: MouseEvent) => void;
}) {
  const pct = Math.round(score * 100);
  const colorCls =
    pct >= 90
      ? "bg-emerald-50 text-emerald-700 ring-emerald-600/20"
      : pct >= 75
        ? "bg-amber-50 text-amber-700 ring-amber-600/20"
        : "bg-red-50 text-red-700 ring-red-600/20";
  const interactive = onClick != null;
  return (
    <button
      type="button"
      disabled={!interactive}
      onClick={onClick}
      className={`inline-flex items-center whitespace-nowrap rounded-full px-1.5 py-0.5 text-[10px] font-semibold ring-1 ring-inset ${colorCls} ${
        interactive
          ? "cursor-pointer hover:opacity-90 focus:outline-none focus-visible:ring-2 focus-visible:ring-black/15"
          : "cursor-default"
      }`}
      title={
        interactive
          ? `Invoice similarity: ${pct}% — click for field breakdown`
          : `Invoice similarity: ${pct}%`
      }
    >
      {pct}% match
    </button>
  );
}

function fieldMatchTypeClass(matchType: string): string {
  if (matchType === "exact") return "text-emerald-700 bg-emerald-50";
  if (matchType === "fuzzy") return "text-amber-700 bg-amber-50";
  return "text-gray-500 bg-gray-100";
}

function formatFieldLabel(name: string): string {
  return name.replace(/_/g, " ").replace(/\b\w/g, (c) => c.toUpperCase());
}

/** Field-by-field comparison panel (used in cards and table accordions). */
function ComparedFieldsPanel({ row }: { row: ReconcileRow }) {
  const fields = row.compared_fields ?? [];
  return (
    <div className="max-w-2xl">
      {row.decision_rule ? (
        <p className="mb-2 text-[12px] text-gray-600">
          Rule fired:{" "}
          <span className="font-semibold text-gray-800">{row.decision_rule}</span>
          {row.decision_confidence ? (
            <span className="text-gray-400"> · {row.decision_confidence}</span>
          ) : null}
        </p>
      ) : null}
      {fields.length === 0 ? (
        <p className="text-[12px] text-gray-500">
          No field comparison was recorded for this row.
        </p>
      ) : (
        <table className="w-full border-collapse text-left text-[12px]">
          <thead>
            <tr className="border-b border-[#E8E8EC] text-[11px] uppercase tracking-wide text-gray-400">
              <th className="pb-1.5 pr-3 font-medium">Field</th>
              <th className="pb-1.5 pr-3 font-medium">Match Type</th>
              <th className="pb-1.5 font-medium">Score</th>
            </tr>
          </thead>
          <tbody>
            {fields.map((f) => (
              <tr
                key={f.field_name}
                className="border-b border-[#EEF0F4] last:border-0"
              >
                <td className="py-1.5 pr-3 font-medium text-gray-800">
                  {formatFieldLabel(f.field_name)}
                </td>
                <td className="py-1.5 pr-3">
                  <span
                    className={`inline-flex rounded px-1.5 py-0.5 text-[11px] font-medium capitalize ${fieldMatchTypeClass(
                      f.match_type
                    )}`}
                  >
                    {f.match_type.replace(/_/g, " ")}
                  </span>
                </td>
                <td className="py-1.5 text-gray-600">
                  {f.field_score != null ? `${f.field_score}%` : "—"}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </div>
  );
}

/** Inline accordion showing engine field-by-field comparison for one invoice. */
function ComparedFieldsAccordionRow({
  row,
  colSpan,
}: {
  row: ReconcileRow;
  colSpan: number;
}) {
  return (
    <tr className="bg-[#F8F9FB]">
      <td colSpan={colSpan} className="px-4 py-3">
        <ComparedFieldsPanel row={row} />
      </td>
    </tr>
  );
}

/** Compact "why?" control — opens the compared_fields accordion without leaving the table. */
function WhyRationaleButton({
  expanded,
  onToggle,
}: {
  expanded: boolean;
  onToggle: (e: MouseEvent) => void;
}) {
  const tResults = useTranslations("results");
  return (
    <button
      type="button"
      onClick={onToggle}
      className={`inline-flex items-center gap-1 rounded-[4px] px-1.5 py-0.5 text-[10px] font-medium transition-colors ${
        expanded
          ? "bg-[#2563EB] text-white"
          : "bg-[#EFF6FF] border border-[#BFDBFE] text-[#2563EB] hover:bg-[#DBEAFE]"
      }`}
      title={expanded ? "Hide match rationale" : "Why this decision?"}
      aria-expanded={expanded}
      aria-label="Why this match decision"
    >
      {tResults("whyButton")}
    </button>
  );
}

type RunSummary = {
  run_id: string;
  client_name: string;
  client_gstin_id?: string;
  client_gstin?: string;
  period: string;
  assigned_to_name: string;
  status: string;
  /** Present when the run failed before writing a results payload. */
  status_message?: string | null;
  finalized_by_name: string | null;
  finalized_at: string | null;
  total_gstr_records: number;
  // Stable canonical fields (guaranteed from backend)
  clean_matched_count: number;
  review_required_count: number;
  total_linked_count: number;
  matched_count: number;          // = clean_matched_count (backward compat)
  exact_match_count?: number;
  missed_itc_count: number;
  missed_itc_total_amount: number;
  missed_itc_amount_paise?: number;
  wrongful_risk_count: number;
  wrongful_risk_total_amount: number;
  wrongful_risk_amount_paise?: number;
  wrongful_risk_purchase_total_amount?: number;
  duplicate_entry_count?: number;
  unmatched_notes_count?: number;
  purchase_value_at_risk_paise?: number;
  late_match_count?: number | null;
  match_rate_percent: number;
  match_rate_pct?: number;        // alias for match_rate_percent
  user_role: "admin" | "staff";
  /** PR rows excluded from matching (e.g. missing invoice number). */
  pr_skipped_count?: number;
  pr_skipped_detail?: string | null;
  /** GSTR-2B ISD / IMPG lines detected but not included in reconciliation. */
  isd_present?: boolean;
  isd_count?: number;
  impg_present?: boolean;
  impg_count?: number;
  isd_impg_warning?: string | null;
};

type ConfidenceSummary = {
  run_id: string;
  total_invoices: number;
  high_confidence: number;
  medium_confidence: number;
  low_confidence: number;
  unmatched: number;
};

function ConfidenceSummaryCard({ data }: { data: ConfidenceSummary }) {
  const { high_confidence, medium_confidence, low_confidence, unmatched, total_invoices } =
    data;
  const total = Math.max(total_invoices, 1);
  const segments = [
    {
      key: "high",
      count: high_confidence,
      label: "High confidence",
      barClass: "bg-emerald-500",
      textClass: "text-emerald-700",
      chipClass: "bg-emerald-50 text-emerald-700",
    },
    {
      key: "medium",
      count: medium_confidence,
      label: "Medium confidence",
      barClass: "bg-amber-500",
      textClass: "text-amber-700",
      chipClass: "bg-amber-50 text-amber-700",
    },
    {
      key: "low",
      count: low_confidence,
      label: "Low confidence",
      barClass: "bg-red-500",
      textClass: "text-red-700",
      chipClass: "bg-red-50 text-red-700",
    },
    {
      key: "unmatched",
      count: unmatched,
      label: "Unmatched",
      barClass: "bg-gray-400",
      textClass: "text-gray-500",
      chipClass: "bg-gray-100 text-gray-600",
    },
  ] as const;

  return (
    <div className="mt-4 rounded-[1.25rem] bg-[#F7F7F8] px-4 py-3">
      <div className="mb-2 flex items-center justify-between gap-2">
        <p className="text-[12px] font-semibold text-[var(--ink)]">Match confidence</p>
        <p className="text-[11px] tabular-nums text-gray-400">
          {total_invoices.toLocaleString("en-IN")} invoices
        </p>
      </div>
      <div className="flex h-2 w-full overflow-hidden rounded-full bg-white">
        {segments.map((seg) =>
          seg.count > 0 ? (
            <div
              key={seg.key}
              className={`h-full ${seg.barClass}`}
              style={{ width: `${(seg.count / total) * 100}%` }}
              title={`${seg.count.toLocaleString("en-IN")} ${seg.label}`}
            />
          ) : null
        )}
      </div>
      <div className="mt-2.5 flex flex-wrap gap-x-3 gap-y-1.5">
        {segments.map((seg) => (
          <span
            key={seg.key}
            className={`inline-flex items-center gap-1 rounded-full px-2.5 py-0.5 text-[11px] font-medium tabular-nums ${seg.chipClass}`}
          >
            <span className="font-semibold">{seg.count.toLocaleString("en-IN")}</span>
            {seg.label}
          </span>
        ))}
      </div>
    </div>
  );
}

/** Shared action button styles for results header / exports */
const actionBtnBase =
  "inline-flex items-center justify-center gap-2 text-[13px] font-semibold transition-opacity disabled:cursor-not-allowed disabled:opacity-50";
const exportToolbarBtn = `${actionBtnBase} h-9 rounded-lg border border-[#e5e7eb] bg-white px-4 text-[#1a1a1a] hover:bg-[#f9fafb]`;
const deleteRunBtn = `inline-flex items-center gap-1.5 text-[0.8rem] font-normal text-[#9ca3af] transition-colors hover:text-red-500 disabled:cursor-not-allowed disabled:opacity-50`;

type Paginated<T> = {
  data: T[];
  total: number;
  page: number;
  limit: number;
  total_pages: number;
};

type Note = {
  id: string;
  author_name: string;
  created_at: string;
  note_text: string;
};

/** Backend returns `note` / `author_full_name`; UI uses `note_text` / `author_name`. */
function mapApiNote(raw: Record<string, unknown>): Note {
  return {
    id: String(raw.id ?? ""),
    author_name: String(
      raw.author_name ?? raw.author_full_name ?? "Unknown"
    ),
    created_at: String(raw.created_at ?? ""),
    note_text: String(raw.note_text ?? raw.note ?? ""),
  };
}

type Toast = { id: string; message: string; type: "success" | "error" };

type LateMatchRow = {
  supplier_gstin: string;
  invoice_number: string;
  original_period: string;
  gstr2b_period: string;
  months_late: number;
};

type FinalizeChecklistState = {
  reviewed_l3_matches: boolean;
  verified_section_17_5: boolean;
  reviewed_rule_37: boolean;
  contacted_suppliers: boolean;
  itc_amounts_verified: boolean;
};

const EMPTY_FINALIZE_CHECKLIST: FinalizeChecklistState = {
  reviewed_l3_matches: false,
  verified_section_17_5: false,
  reviewed_rule_37: false,
  contacted_suppliers: false,
  itc_amounts_verified: false,
};

const FINALIZE_CHECKLIST_ROWS: {
  key: keyof FinalizeChecklistState;
  label: string;
}[] = [
  {
    key: "reviewed_l3_matches",
    label: "I have reviewed all matches requiring human review",
  },
  {
    key: "verified_section_17_5",
    label: "I have verified all Section 17(5) flagged invoices",
  },
  {
    key: "reviewed_rule_37",
    label: "I have reviewed all Rule 37 payment deadline warnings",
  },
  {
    key: "contacted_suppliers",
    label:
      "I have contacted suppliers with missing GSTR filings (if any)",
  },
  {
    key: "itc_amounts_verified",
    label: "All ITC amounts match what I plan to claim in GSTR-3B",
  },
];

// ─── Helpers ───────────────────────────────────────────────────────────────

function formatDate(isoString: string): string {
  const d = new Date(isoString);
  if (Number.isNaN(d.getTime())) return "—";
  const day = d.getDate();
  const mon = d.toLocaleString("en-GB", { month: "short" });
  const y = d.getFullYear();
  return `${day} ${mon} ${y}`;
}

function timeAgo(isoString: string): string {
  const t = new Date(isoString).getTime();
  if (Number.isNaN(t)) return "—";
  const s = Math.floor((Date.now() - t) / 1000);
  if (s < 10) return "just now";
  if (s < 60) return `${s}s ago`;
  const m = Math.floor(s / 60);
  if (m < 60) return `${m}m ago`;
  const h = Math.floor(m / 60);
  if (h < 48) return `${h}h ago`;
  const days = Math.floor(h / 24);
  return `${days} day${days === 1 ? "" : "s"} ago`;
}

function getImpactLevel(
  amount: number,
  maxAmount: number
): "high" | "medium" | "low" {
  if (maxAmount <= 0) return "low";
  if (amount >= maxAmount * 0.5) return "high";
  if (amount >= maxAmount * 0.1) return "medium";
  return "low";
}

const COMPARE_FIELDS: { label: string; keys: string[] }[] = [
  { label: "GSTIN", keys: ["gstin", "GSTIN", "supplier_gstin", "Supplier GSTIN"] },
  {
    label: "Invoice Number",
    keys: ["invoice_number", "Invoice Number", "invoice_no", "Invoice No"],
  },
  {
    label: "Invoice Date",
    keys: ["invoice_date", "Invoice Date", "date", "invoice_dt"],
  },
  {
    label: "Taxable Amount",
    keys: ["taxable_amount", "Taxable Amount", "taxable", "taxable_val"],
  },
  { label: "IGST", keys: ["igst", "IGST", "integrated_tax"] },
  { label: "CGST", keys: ["cgst", "CGST", "central_tax"] },
  { label: "SGST", keys: ["sgst", "SGST", "state_tax"] },
];

const COMPARE_AMOUNT_LABELS = new Set([
  "Taxable Amount",
  "IGST",
  "CGST",
  "SGST",
]);

function formatCompareFieldDisplay(label: string, raw: string): string {
  if (raw === "—" || !COMPARE_AMOUNT_LABELS.has(label)) return raw;
  const n = Number(String(raw).replace(/,/g, ""));
  if (!Number.isFinite(n)) return raw;
  return formatINR(n);
}

function readDataField(
  obj: Record<string, string | number>,
  keys: string[]
): string {
  for (const k of keys) {
    if (k in obj && obj[k] !== undefined && obj[k] !== null && obj[k] !== "")
      return String(obj[k]);
  }
  return "—";
}

function normCompare(a: string, b: string): boolean {
  return a.trim().toLowerCase() === b.trim().toLowerCase();
}

function DecisionDiagnosticsBlock({ row }: { row: ReconcileRow }) {
  if (!row.decision_rule) return null;
  return (
    <div className="mt-2 space-y-1 text-xs text-gray-500">
      <div>
        <span className="font-medium">Rule:</span> {row.decision_rule} ·{" "}
        {row.decision_confidence ?? "—"}
      </div>
      {row.decision_matched_fields != null &&
        row.decision_matched_fields.length > 0 && (
          <div>✅ Matched: {row.decision_matched_fields.join(", ")}</div>
        )}
      {row.decision_differed_fields != null &&
        row.decision_differed_fields.length > 0 && (
          <div>⚠️ Differed: {row.decision_differed_fields.join(", ")}</div>
        )}
      {row.decision_normalized_pairs != null &&
        row.decision_normalized_pairs.length > 0 && (
          <div>
            🔄 Normalized:{" "}
            {row.decision_normalized_pairs
              .map(([a, b]) => `${a} → ${b}`)
              .join(", ")}
          </div>
        )}
    </div>
  );
}

type FetcherKey = readonly [path: string, token: string];

async function authJsonFetcher<T>([path, token]: FetcherKey): Promise<T> {
  return apiFetch<T>(path, { token });
}

/** Shared `?sort=` values for reconcile bucket APIs + client-side duplicate sort. */
type ReconcileSortValue =
  | "amount_desc"
  | "amount_asc"
  | "invoice_date_desc"
  | "invoice_date_asc"
  | "confidence_asc"
  | "supplier_name";

const RECONCILE_SORT_OPTIONS_BASE: { value: ReconcileSortValue; label: string }[] =
  [
    { value: "amount_desc", label: "Amount: High to Low" },
    { value: "amount_asc", label: "Amount: Low to High" },
    { value: "invoice_date_desc", label: "Date: Newest first" },
    { value: "invoice_date_asc", label: "Date: Oldest first" },
    { value: "supplier_name", label: "Supplier name: A–Z" },
  ];

const RECONCILE_SORT_OPTIONS_WITH_CONFIDENCE: {
  value: ReconcileSortValue;
  label: string;
}[] = [
  ...RECONCILE_SORT_OPTIONS_BASE.slice(0, 4),
  { value: "confidence_asc", label: "Confidence: Low to High" },
  ...RECONCILE_SORT_OPTIONS_BASE.slice(4),
];

function sortDuplicateEntryRows<
  T extends {
    id: string;
    amount: number | null;
    invoice_date: string | null;
    supplier_gstin: string;
    supplier_name?: string | null;
  },
>(rows: T[], sort: ReconcileSortValue): T[] {
  const out = [...rows];
  const idKey = (r: T) => String(r.id);
  if (sort === "amount_asc") {
    out.sort((a, b) => Math.abs(a.amount ?? 0) - Math.abs(b.amount ?? 0) || idKey(a).localeCompare(idKey(b)));
  } else if (sort === "amount_desc") {
    out.sort((a, b) => Math.abs(b.amount ?? 0) - Math.abs(a.amount ?? 0) || idKey(a).localeCompare(idKey(b)));
  } else if (sort === "invoice_date_asc") {
    out.sort((a, b) =>
      String(a.invoice_date || "9999-12-31").localeCompare(String(b.invoice_date || "9999-12-31")) ||
      idKey(a).localeCompare(idKey(b))
    );
  } else if (sort === "invoice_date_desc") {
    out.sort((a, b) =>
      String(b.invoice_date || "").localeCompare(String(a.invoice_date || "")) ||
      idKey(a).localeCompare(idKey(b))
    );
  } else if (sort === "supplier_name") {
    out.sort((a, b) => {
      const an = String(a.supplier_name || a.supplier_gstin || "").toLowerCase();
      const bn = String(b.supplier_name || b.supplier_gstin || "").toLowerCase();
      return an.localeCompare(bn) || idKey(a).localeCompare(idKey(b));
    });
  }
  return out;
}

function buildMatchedQuery(
  page: number,
  limit: number,
  search: string,
  sort: string,
  f: {
    match_level: string;
    has_notes: boolean;
    section_17_5: boolean;
    amount_min: string;
    amount_max: string;
    ims_status: string;
    /** When true, forces review_required=true in the query (Review Required tab). */
    force_review_required?: boolean;
  }
): string {
  const p = new URLSearchParams();
  p.set("page", String(page));
  p.set("limit", String(limit));
  p.set("sort", sort);
  const q = search.trim();
  if (q) p.set("search", q);
  if (f.match_level) p.set("match_level", f.match_level);
  if (f.has_notes) p.set("has_notes", "true");
  if (f.force_review_required) p.set("review_required", "true");
  if (f.section_17_5) p.set("section_17_5", "true");
  if (f.amount_min.trim()) p.set("amount_min", f.amount_min.trim());
  if (f.amount_max.trim()) p.set("amount_max", f.amount_max.trim());
  if (f.ims_status.trim()) p.set("ims_status", f.ims_status.trim());
  return p.toString();
}

function hasActiveMatchedFilters(
  search: string,
  f: {
    match_level: string;
    has_notes: boolean;
    section_17_5: boolean;
    amount_min: string;
    amount_max: string;
    ims_status: string;
  }
): boolean {
  return (
    !!search.trim() ||
    !!f.match_level ||
    f.has_notes ||
    f.section_17_5 ||
    !!f.amount_min.trim() ||
    !!f.amount_max.trim() ||
    !!f.ims_status.trim()
  );
}

type ItcFiltersState = {
  amount_min: string;
  amount_max: string;
  supplier_gstin: string;
  date_from: string;
  date_to: string;
  ims_status: string;
};

type RiskFiltersState = {
  amount_min: string;
  amount_max: string;
  supplier_gstin: string;
  risk_level: string;
};

function buildItcListQueryString(
  page: number,
  limit: number,
  sort: string,
  f: ItcFiltersState
): string {
  const p = new URLSearchParams();
  p.set("page", String(page));
  p.set("limit", String(limit));
  p.set("sort", sort);
  if (f.amount_min.trim()) p.set("amount_min", f.amount_min.trim());
  if (f.amount_max.trim()) p.set("amount_max", f.amount_max.trim());
  if (f.supplier_gstin.trim()) p.set("supplier_gstin", f.supplier_gstin.trim());
  if (f.date_from.trim()) p.set("date_from", f.date_from.trim());
  if (f.date_to.trim()) p.set("date_to", f.date_to.trim());
  if (f.ims_status.trim()) p.set("ims_status", f.ims_status.trim());
  return p.toString();
}

function buildItcExportQueryString(sort: string, f: ItcFiltersState): string {
  const p = new URLSearchParams();
  p.set("sort", sort);
  if (f.amount_min.trim()) p.set("amount_min", f.amount_min.trim());
  if (f.amount_max.trim()) p.set("amount_max", f.amount_max.trim());
  if (f.supplier_gstin.trim()) p.set("supplier_gstin", f.supplier_gstin.trim());
  if (f.date_from.trim()) p.set("date_from", f.date_from.trim());
  if (f.date_to.trim()) p.set("date_to", f.date_to.trim());
  if (f.ims_status.trim()) p.set("ims_status", f.ims_status.trim());
  return p.toString();
}

function hasActiveItcFilters(f: ItcFiltersState): boolean {
  return Object.values(f).some((v) => String(v).trim() !== "");
}

function buildRiskListQueryString(
  page: number,
  limit: number,
  sort: string,
  f: RiskFiltersState
): string {
  const p = new URLSearchParams();
  p.set("page", String(page));
  p.set("limit", String(limit));
  p.set("sort", sort);
  if (f.amount_min.trim()) p.set("amount_min", f.amount_min.trim());
  if (f.amount_max.trim()) p.set("amount_max", f.amount_max.trim());
  if (f.supplier_gstin.trim()) p.set("supplier_gstin", f.supplier_gstin.trim());
  if (f.risk_level.trim()) p.set("risk_level", f.risk_level.trim().toLowerCase());
  return p.toString();
}

function buildRiskExportQueryString(sort: string, f: RiskFiltersState): string {
  const p = new URLSearchParams();
  p.set("sort", sort);
  if (f.amount_min.trim()) p.set("amount_min", f.amount_min.trim());
  if (f.amount_max.trim()) p.set("amount_max", f.amount_max.trim());
  if (f.supplier_gstin.trim()) p.set("supplier_gstin", f.supplier_gstin.trim());
  if (f.risk_level.trim()) p.set("risk_level", f.risk_level.trim().toLowerCase());
  return p.toString();
}

function hasActiveRiskFilters(f: RiskFiltersState): boolean {
  return Object.values(f).some((v) => String(v).trim() !== "");
}

function supplierRiskImpactLabel(
  supplierTotal: number,
  grandTotal: number
): "high" | "medium" | "low" {
  if (grandTotal <= 0) return "low";
  if (supplierTotal >= grandTotal * 0.5) return "high";
  if (supplierTotal >= grandTotal * 0.1) return "medium";
  return "low";
}

// ─── Small UI bits ─────────────────────────────────────────────────────────

function MatchLevelBadge({ level }: { level: MatchLevel }) {
  if (level === "EXACT") {
    return (
      <span className="inline-flex items-center gap-1 rounded-[4px] px-1.5 py-0.5 text-[10px] font-semibold bg-[#DCFCE7] text-[#166534]">
        Exact L1
      </span>
    );
  }
  if (level === "FUZZY") {
    return (
      <span className="inline-flex items-center gap-1 rounded-[4px] px-1.5 py-0.5 text-[10px] font-semibold bg-[#FEF9C3] text-[#713F12]">
        Fuzzy L3
      </span>
    );
  }
  if (level === "MANUAL") {
    return (
      <span className="inline-flex items-center gap-1 rounded-[4px] px-1.5 py-0.5 text-[10px] font-semibold bg-[#F0F9FF] text-[#0369A1]">
        Soft L2
      </span>
    );
  }
  return (
    <span className="inline-flex items-center gap-1 rounded-[4px] px-1.5 py-0.5 text-[10px] font-semibold bg-[#F1F5F9] text-[#475569]">
      {level}
    </span>
  );
}

function SectionError({
  message,
  onRetry,
}: {
  message: string;
  onRetry: () => void;
}) {
  return (
    <div className="rounded-2xl border border-red-200 bg-white p-4 text-[13px] text-red-600">
      {message}{" "}
      <button
        type="button"
        className="min-h-[44px] font-medium underline"
        onClick={onRetry}
      >
        Retry
      </button>
    </div>
  );
}

function SummarySkeleton() {
  return (
    <div className="flex w-full animate-pulse flex-wrap gap-4 py-2">
      <div className="h-6 w-48 rounded bg-gray-200" />
      <div className="h-6 w-32 rounded bg-gray-200" />
      <div className="h-6 w-40 rounded bg-gray-200" />
      <div className="h-6 w-24 rounded bg-gray-200" />
    </div>
  );
}

// ─── Page ────────────────────────────────────────────────────────────────────

export default function ReconcileResultsPage() {
  const tResults = useTranslations("results");
  const tCommon = useTranslations("common");
  const locale = useLocale();
  const params = useParams();
  const router = useRouter();
  const runId = typeof params.run_id === "string" ? params.run_id : "";

  const tokenState = useAccessToken();
  // null  = still resolving (show skeleton)
  // false = resolved, no session (middleware should redirect, but guard anyway)
  // string = resolved, authenticated
  const authLoading = tokenState === null;
  const authToken =
    typeof tokenState === "string" && tokenState.length > 0
      ? tokenState
      : null;

  const [riskPage, setRiskPage] = useState(1);
  const [itcPage, setItcPage] = useState(1);
  const [matchedPage, setMatchedPage] = useState(1);
  const [matchedPageSize, setMatchedPageSize] = useState(() =>
    readStoredReconcileTablePageSize(RECONCILE_PAGE_SIZE_STORAGE_KEYS.matched)
  );
  const [reviewRequiredPage, setReviewRequiredPage] = useState(1);
  const [reviewRequiredPageSize, setReviewRequiredPageSize] = useState(() =>
    readStoredReconcileTablePageSize(RECONCILE_PAGE_SIZE_STORAGE_KEYS.review_required)
  );
  const [itcPageSize, setItcPageSize] = useState(() =>
    readStoredReconcileTablePageSize(RECONCILE_PAGE_SIZE_STORAGE_KEYS.itc)
  );
  const [riskPageSize, setRiskPageSize] = useState(() =>
    readStoredReconcileTablePageSize(RECONCILE_PAGE_SIZE_STORAGE_KEYS.risk)
  );
  const [rule37PageSize, setRule37PageSize] = useState(() =>
    readStoredReconcileTablePageSize(RECONCILE_PAGE_SIZE_STORAGE_KEYS.rule37)
  );
  const [rule37Page, setRule37Page] = useState(1);
  const [section17PageSize, setSection17PageSize] = useState(() =>
    readStoredReconcileTablePageSize(RECONCILE_PAGE_SIZE_STORAGE_KEYS.section17)
  );
  const [section17Page, setSection17Page] = useState(1);

  const [resultsTab, setResultsTab] = useState<ResultsBucketTabId>("matched");
  const [itcGroupBySupplier, setItcGroupBySupplier] = useState(false);
  const [riskGroupBySupplier, setRiskGroupBySupplier] = useState(false);
  const [itcExpandedSupplier, setItcExpandedSupplier] = useState<string | null>(
    null
  );
  const [riskExpandedSupplier, setRiskExpandedSupplier] = useState<
    string | null
  >(null);
  const [rationaleExpandedId, setRationaleExpandedId] = useState<string | null>(
    null
  );

  const toggleRationale = useCallback(
    (e: MouseEvent, rowId: string) => {
      e.stopPropagation();
      setRationaleExpandedId((prev) => (prev === rowId ? null : rowId));
    },
    []
  );
  const [rule37Open, setRule37Open] = useState(false);
  const [section17Open, setSection17Open] = useState(false);

  useEffect(() => {
    setRationaleExpandedId(null);
  }, [resultsTab]);

  useEffect(() => {
    if (resultsTab === "rule37") {
      setRule37Open(true);
    }
    if (resultsTab === "section17") {
      setSection17Open(true);
    }
  }, [resultsTab]);

  const [selectedIds, setSelectedIds] = useState<{
    itc: Set<string>;
    risk: Set<string>;
  }>(() => ({ itc: new Set(), risk: new Set() }));

  const [followupLetterRows, setFollowupLetterRows] = useState<
    ReconcileRow[] | null
  >(null);
  const [followupSelectionHint, setFollowupSelectionHint] = useState<
    string | null
  >(null);

  const [activeRecord, setActiveRecord] = useState<ReconcileRow | null>(null);
  const [newNoteText, setNewNoteText] = useState("");
  const [notePosting, setNotePosting] = useState(false);
  const [notePostError, setNotePostError] = useState<string | null>(null);

  const [matchedSearch, setMatchedSearch] = useState("");
  const [debouncedMatchedSearch, setDebouncedMatchedSearch] = useState("");
  const [reviewRequiredSearch, setReviewRequiredSearch] = useState("");
  const [debouncedReviewRequiredSearch, setDebouncedReviewRequiredSearch] = useState("");

  const [docTypeFilterMatched, setDocTypeFilterMatched] = useState<string>("");
  const [docTypeFilterReviewRequired, setDocTypeFilterReviewRequired] = useState<string>("");
  const [docTypeFilterItc, setDocTypeFilterItc] = useState<string>("");
  const [docTypeFilterRisk, setDocTypeFilterRisk] = useState<string>("");

  const checkDocType = (row: any, filterVal: string) => {
    if (!filterVal) return true;
    const rawDt = String(
      row?.document_type ||
      row?.gstr2b_data?.document_type ||
      row?.gstr2b_data?.doc_type ||
      row?.pr_data?.document_type ||
      "Invoice"
    );
    const dt = rawDt.toLowerCase().replace("_", " ").trim();
    const f = filterVal.toLowerCase().replace("_", " ").trim();
    return dt === f;
  };

  useEffect(() => {
    const h = window.setTimeout(() => setDebouncedMatchedSearch(matchedSearch), 400);
    return () => window.clearTimeout(h);
  }, [matchedSearch]);

  useEffect(() => {
    const h = window.setTimeout(() => setDebouncedReviewRequiredSearch(reviewRequiredSearch), 400);
    return () => window.clearTimeout(h);
  }, [reviewRequiredSearch]);

  const [matchedFilters, setMatchedFilters] = useState({
    match_level: "",
    has_notes: false,
    // review_required is no longer a filter in the Matched tab — those records have their own tab
    section_17_5: false,
    amount_min: "",
    amount_max: "",
    ims_status: "",
  });

  const [reviewRequiredFilters, setReviewRequiredFilters] = useState({
    match_level: "",
    has_notes: false,
    section_17_5: false,
    amount_min: "",
    amount_max: "",
    ims_status: "",
  });

  /** Defaults: Matched → newest date; Review Required → lowest confidence first. */
  const [matchedSort, setMatchedSort] =
    useState<ReconcileSortValue>("invoice_date_desc");
  const [reviewRequiredSort, setReviewRequiredSort] =
    useState<ReconcileSortValue>("confidence_asc");
  const [duplicateEntrySort, setDuplicateEntrySort] =
    useState<ReconcileSortValue>("amount_desc");

  useEffect(() => {
    setMatchedPage(1);
  }, [debouncedMatchedSearch, matchedFilters, matchedPageSize, matchedSort]);

  useEffect(() => {
    setReviewRequiredPage(1);
  }, [
    debouncedReviewRequiredSearch,
    reviewRequiredFilters,
    reviewRequiredPageSize,
    reviewRequiredSort,
  ]);

  const handleTablePageSizeChange = useCallback(
    (
      storageKey: string,
      size: number,
      setPageSize: (n: number) => void,
      setPage: (fn: (p: number) => number) => void
    ) => {
      if (!isValidReconcileTablePageSize(size)) return;
      setPageSize(size);
      setPage(() => 1);
      persistReconcileTablePageSize(storageKey, size);
    },
    []
  );

  const handleMatchedPageSizeChange = useCallback(
    (size: number) => {
      handleTablePageSizeChange(
        RECONCILE_PAGE_SIZE_STORAGE_KEYS.matched,
        size,
        setMatchedPageSize,
        setMatchedPage
      );
    },
    [handleTablePageSizeChange]
  );

  const handleReviewRequiredPageSizeChange = useCallback(
    (size: number) => {
      handleTablePageSizeChange(
        RECONCILE_PAGE_SIZE_STORAGE_KEYS.review_required,
        size,
        setReviewRequiredPageSize,
        setReviewRequiredPage
      );
    },
    [handleTablePageSizeChange]
  );

  const handleItcPageSizeChange = useCallback(
    (size: number) => {
      handleTablePageSizeChange(
        RECONCILE_PAGE_SIZE_STORAGE_KEYS.itc,
        size,
        setItcPageSize,
        setItcPage
      );
    },
    [handleTablePageSizeChange]
  );

  const handleRiskPageSizeChange = useCallback(
    (size: number) => {
      handleTablePageSizeChange(
        RECONCILE_PAGE_SIZE_STORAGE_KEYS.risk,
        size,
        setRiskPageSize,
        setRiskPage
      );
    },
    [handleTablePageSizeChange]
  );

  const handleRule37PageSizeChange = useCallback(
    (size: number) => {
      handleTablePageSizeChange(
        RECONCILE_PAGE_SIZE_STORAGE_KEYS.rule37,
        size,
        setRule37PageSize,
        setRule37Page
      );
    },
    [handleTablePageSizeChange]
  );

  const handleSection17PageSizeChange = useCallback(
    (size: number) => {
      handleTablePageSizeChange(
        RECONCILE_PAGE_SIZE_STORAGE_KEYS.section17,
        size,
        setSection17PageSize,
        setSection17Page
      );
    },
    [handleTablePageSizeChange]
  );

  const [itcFilters, setItcFilters] = useState<ItcFiltersState>({
    amount_min: "",
    amount_max: "",
    supplier_gstin: "",
    date_from: "",
    date_to: "",
    ims_status: "",
  });
  const [debouncedItcFilters, setDebouncedItcFilters] =
    useState<ItcFiltersState>(itcFilters);
  useEffect(() => {
    const h = window.setTimeout(() => setDebouncedItcFilters(itcFilters), 400);
    return () => window.clearTimeout(h);
  }, [itcFilters]);

  const [itcSort, setItcSort] = useState<ReconcileSortValue>("amount_desc");

  useEffect(() => {
    setItcPage(1);
  }, [debouncedItcFilters, itcSort, itcPageSize]);

  const [riskFilters, setRiskFilters] = useState<RiskFiltersState>({
    amount_min: "",
    amount_max: "",
    supplier_gstin: "",
    risk_level: "",
  });
  const [debouncedRiskFilters, setDebouncedRiskFilters] =
    useState<RiskFiltersState>(riskFilters);
  useEffect(() => {
    const h = window.setTimeout(() => setDebouncedRiskFilters(riskFilters), 400);
    return () => window.clearTimeout(h);
  }, [riskFilters]);

  const [riskSort, setRiskSort] = useState<ReconcileSortValue>("amount_desc");

  useEffect(() => {
    setRiskPage(1);
  }, [debouncedRiskFilters, riskSort, riskPageSize]);

  const [localDecisionStatus, setLocalDecisionStatus] = useState<
    Map<string, DecisionStatus>
  >(() => new Map());
  const [localRule37ActionStatus, setLocalRule37ActionStatus] = useState<
    Map<string, Rule37ActionStatus>
  >(() => new Map());
  const [rule37SummaryRefreshKey, setRule37SummaryRefreshKey] = useState(0);
  const [rule37UpdatingIds, setRule37UpdatingIds] = useState<Set<string>>(
    () => new Set()
  );
  const [rule37MarkPaidTarget, setRule37MarkPaidTarget] =
    useState<Rule37MarkPaidTarget | null>(null);

  const [toasts, setToasts] = useState<Toast[]>([]);
  const addToast = useCallback((message: string, type: Toast["type"]) => {
    const id = `${Date.now()}-${Math.random().toString(36).slice(2)}`;
    setToasts((prev) => [...prev, { id, message, type }]);
    window.setTimeout(() => {
      setToasts((prev) => prev.filter((t) => t.id !== id));
    }, 3000);
  }, []);

  const [itcCsvDownloading, setItcCsvDownloading] = useState(false);
  const [riskCsvDownloading, setRiskCsvDownloading] = useState(false);
  const [excelDownloading, setExcelDownloading] = useState(false);
  const [pdfDownloading, setPdfDownloading] = useState(false);

  const [autoApproveThreshold, setAutoApproveThreshold] = useState(
    DEFAULT_AUTO_APPROVE_THRESHOLD
  );
  const [autoApproveSaving, setAutoApproveSaving] = useState(false);

  const downloadItcCsv = useCallback(async () => {
    if (!authToken || !runId) return;
    setItcCsvDownloading(true);
    try {
      const qs = buildItcExportQueryString(itcSort, debouncedItcFilters);
      const res = await fetch(
        `${API_URL}/api/reconcile/runs/${runId}/export/itc?${qs}`,
        { headers: { Authorization: `Bearer ${authToken}` } }
      );
      if (!res.ok) throw new Error("failed");
      const blob = await res.blob();
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = "itc-export.csv";
      document.body.appendChild(a);
      a.click();
      a.remove();
      URL.revokeObjectURL(url);
    } catch {
      addToast("Failed to download CSV", "error");
    } finally {
      setItcCsvDownloading(false);
    }
  }, [addToast, authToken, debouncedItcFilters, itcSort, runId]);

  const downloadRiskCsv = useCallback(async () => {
    if (!authToken || !runId) return;
    setRiskCsvDownloading(true);
    try {
      const qs = buildRiskExportQueryString(riskSort, debouncedRiskFilters);
      const res = await fetch(
        `${API_URL}/api/reconcile/runs/${runId}/export/risk?${qs}`,
        { headers: { Authorization: `Bearer ${authToken}` } }
      );
      if (!res.ok) throw new Error("failed");
      const blob = await res.blob();
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = "risk-export.csv";
      document.body.appendChild(a);
      a.click();
      a.remove();
      URL.revokeObjectURL(url);
    } catch {
      addToast("Failed to download CSV", "error");
    } finally {
      setRiskCsvDownloading(false);
    }
  }, [addToast, authToken, debouncedRiskFilters, riskSort, runId]);

  const downloadExcelReport = useCallback(async () => {
    if (!authToken || !runId) return;
    setExcelDownloading(true);
    try {
      // Always request the full multi-sheet workbook — never scope by active tab.
      const res = await fetch(
        `${API_URL}/api/reconcile/runs/${runId}/export/excel`,
        { headers: { Authorization: `Bearer ${authToken}` } }
      );
      if (!res.ok) throw new Error("failed");
      const blob = await res.blob();
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = "ReconDesk-report.xlsx";
      document.body.appendChild(a);
      a.click();
      a.remove();
      URL.revokeObjectURL(url);
    } catch {
      addToast("Failed to generate Excel report", "error");
    } finally {
      setExcelDownloading(false);
    }
  }, [addToast, authToken, runId]);

  const [drawerDecisionError, setDrawerDecisionError] = useState<string | null>(
    null
  );
  const [finalizeModalOpen, setFinalizeModalOpen] = useState(false);
  const [checklist, setChecklist] = useState<FinalizeChecklistState>(() => ({
    ...EMPTY_FINALIZE_CHECKLIST,
  }));
  const [finalizing, setFinalizing] = useState(false);

  const [deleteModalOpen, setDeleteModalOpen] = useState(false);
  const [deleting, setDeleting] = useState(false);
  const [deleteError, setDeleteError] = useState<string | null>(null);

  useEffect(() => {
    if (finalizeModalOpen) {
      setChecklist({ ...EMPTY_FINALIZE_CHECKLIST });
    }
  }, [finalizeModalOpen]);

  const summaryRef = useRef<HTMLDivElement>(null);

  const authReady = Boolean(authToken);

  const summaryKey = useMemo(
    () =>
      authReady && runId
        ? ([`/api/reconcile/runs/${runId}/summary`, authToken] as const)
        : null,
    [authReady, runId, authToken]
  );

  useEffect(() => {
    console.log("[results] authReady:", authReady, "| summaryKey:", summaryKey ? summaryKey[0] : "null (waiting for auth)");
  }, [authReady, summaryKey]);

  const {
    data: summary,
    error: summaryError,
    isLoading: summaryLoading,
    mutate: mutateSummary,
  } = useSWR<RunSummary>(summaryKey, authJsonFetcher, {
    revalidateOnFocus: false,
  });

  const confidenceSummaryKey = useMemo(
    () =>
      authReady && runId && summary && !summaryError
        ? ([
            `/api/reconcile/runs/${runId}/confidence-summary`,
            authToken,
          ] as const)
        : null,
    [authReady, runId, authToken, summary, summaryError]
  );

  const { data: confidenceSummary } = useSWR<ConfidenceSummary>(
    confidenceSummaryKey,
    authJsonFetcher,
    { revalidateOnFocus: false }
  );

  const isRunFinalized = Boolean(
    summary &&
      (summary.status === "final" || summary.status === "FINAL")
  );

  const downloadPdfReport = useCallback(async () => {
    if (!authToken || !runId || !summary) return;
    setPdfDownloading(true);
    try {
      const itcFilterQuery =
        resultsTab === "itc"
          ? buildItcExportQueryString(itcSort, debouncedItcFilters)
          : undefined;
      const riskFilterQuery =
        resultsTab === "risk"
          ? buildRiskExportQueryString(riskSort, debouncedRiskFilters)
          : undefined;
      const dataset = await fetchReconciliationReportData(
        authToken,
        runId,
        summary,
        { itcFilterQuery, riskFilterQuery }
      );
      const blob = await buildReconciliationReportPdf(dataset);
      downloadBlobAsFile(
        blob,
        reportPdfFilename(
          summary.client_gstin ?? "",
          summary.period ?? ""
        )
      );
    } catch {
      addToast("Failed to generate PDF report", "error");
    } finally {
      setPdfDownloading(false);
    }
  }, [
    addToast,
    authToken,
    debouncedItcFilters,
    debouncedRiskFilters,
    itcSort,
    resultsTab,
    riskSort,
    runId,
    summary,
  ]);

  const itcListQuery = useMemo(
    () =>
      buildItcListQueryString(
        itcPage,
        itcPageSize,
        itcSort,
        debouncedItcFilters
      ),
    [itcPage, itcPageSize, itcSort, debouncedItcFilters]
  );

  const itcListKey = useMemo(() => {
    if (
      !authReady ||
      !runId ||
      !summary ||
      resultsTab !== "itc" ||
      itcGroupBySupplier ||
      summary.missed_itc_count <= 0
    )
      return null;
    return [
      `/api/reconcile/runs/${runId}/itc?${itcListQuery}`,
      authToken,
    ] as const;
  }, [
    authReady,
    runId,
    summary,
    itcListQuery,
    authToken,
    resultsTab,
    itcGroupBySupplier,
  ]);

  const {
    data: itcPageData,
    error: itcError,
    isLoading: itcLoading,
    mutate: mutateItc,
  } = useSWR<Paginated<ReconcileRow>>(itcListKey, authJsonFetcher, {
    revalidateOnFocus: false,
  });

  const itcAllRowsKey = useMemo(() => {
    if (
      !authReady ||
      !runId ||
      !summary ||
      !itcGroupBySupplier ||
      resultsTab !== "itc" ||
      summary.missed_itc_count <= 0
    )
      return null;
    return [
      "itc-all-grouped",
      runId,
      itcSort,
      debouncedItcFilters,
      authToken,
    ] as const;
  }, [
    authReady,
    runId,
    summary,
    itcGroupBySupplier,
    resultsTab,
    itcSort,
    debouncedItcFilters,
    authToken,
  ]);

  const {
    data: itcAllRows,
    error: itcAllRowsError,
    isLoading: itcAllRowsLoading,
    mutate: mutateItcAllRows,
  } = useSWR<ReconcileRow[]>(
    itcAllRowsKey,
    async ([, rid, sort, filters, token]: readonly [
      "itc-all-grouped",
      string,
      ReconcileSortValue,
      ItcFiltersState,
      string,
    ]) =>
      fetchAllBucketPages<ReconcileRow>(async (page, limit) => {
        const qs = buildItcListQueryString(page, limit, sort, filters);
        return apiFetch<Paginated<ReconcileRow>>(
          `/api/reconcile/runs/${rid}/itc?${qs}`,
          { token }
        );
      }, 250),
    { revalidateOnFocus: false }
  );

  const itcSupplierGroups = useMemo(
    () =>
      groupRowsBySupplier(
        (itcAllRows ?? []).filter((r) => checkDocType(r, docTypeFilterItc))
      ),
    [itcAllRows, docTypeFilterItc]
  );

  const riskListQuery = useMemo(
    () =>
      buildRiskListQueryString(
        riskPage,
        riskPageSize,
        riskSort,
        debouncedRiskFilters
      ),
    [riskPage, riskPageSize, riskSort, debouncedRiskFilters]
  );

  const riskListKey = useMemo(() => {
    if (
      !authReady ||
      !runId ||
      !summary ||
      resultsTab !== "risk" ||
      riskGroupBySupplier ||
      summary.wrongful_risk_count <= 0
    )
      return null;
    return [
      `/api/reconcile/runs/${runId}/risk?${riskListQuery}`,
      authToken,
    ] as const;
  }, [
    authReady,
    runId,
    summary,
    riskListQuery,
    authToken,
    resultsTab,
    riskGroupBySupplier,
  ]);

  const {
    data: riskPageData,
    error: riskError,
    isLoading: riskLoading,
    mutate: mutateRisk,
  } = useSWR<Paginated<ReconcileRow>>(riskListKey, authJsonFetcher, {
    revalidateOnFocus: false,
  });

  const riskAllRowsKey = useMemo(() => {
    if (
      !authReady ||
      !runId ||
      !summary ||
      !riskGroupBySupplier ||
      resultsTab !== "risk" ||
      summary.wrongful_risk_count <= 0
    )
      return null;
    return [
      "risk-all-grouped",
      runId,
      riskSort,
      debouncedRiskFilters,
      authToken,
    ] as const;
  }, [
    authReady,
    runId,
    summary,
    riskGroupBySupplier,
    resultsTab,
    riskSort,
    debouncedRiskFilters,
    authToken,
  ]);

  const {
    data: riskAllRows,
    error: riskAllRowsError,
    isLoading: riskAllRowsLoading,
    mutate: mutateRiskAllRows,
  } = useSWR<ReconcileRow[]>(
    riskAllRowsKey,
    async ([, rid, sort, filters, token]: readonly [
      "risk-all-grouped",
      string,
      ReconcileSortValue,
      RiskFiltersState,
      string,
    ]) =>
      fetchAllBucketPages<ReconcileRow>(async (page, limit) => {
        const qs = buildRiskListQueryString(page, limit, sort, filters);
        return apiFetch<Paginated<ReconcileRow>>(
          `/api/reconcile/runs/${rid}/risk?${qs}`,
          { token }
        );
      }, 250),
    { revalidateOnFocus: false }
  );

  const riskSupplierGroups = useMemo(
    () =>
      groupRowsBySupplier(
        (riskAllRows ?? []).filter((r) => checkDocType(r, docTypeFilterRisk))
      ),
    [riskAllRows, docTypeFilterRisk]
  );

  const duplicateEntryListKey = useMemo(() => {
    if (
      !authReady ||
      !runId ||
      !summary ||
      resultsTab !== "duplicate_entry" ||
      (summary.duplicate_entry_count ?? 0) <= 0
    )
      return null;
    // Backend mounts this on /api/reconciliation (not /api/reconcile).
    return [
      `/api/reconciliation/results/${runId}/invoices?category=duplicate_entry&page=1&page_size=200`,
      authToken,
    ] as const;
  }, [authReady, runId, summary, authToken, resultsTab]);

  const unmatchedNotesListKey = useMemo(() => {
    if (
      !authReady ||
      !runId ||
      !summary ||
      resultsTab !== "unmatched_notes" ||
      (summary.unmatched_notes_count ?? 0) <= 0
    )
      return null;
    return [
      `/api/reconciliation/results/${runId}/invoices?category=unmatched_notes&page=1&page_size=200`,
      authToken,
    ] as const;
  }, [authReady, runId, summary, authToken, resultsTab]);

  const {
    data: duplicateEntryData,
    error: duplicateEntryError,
    isLoading: duplicateEntryLoading,
  } = useSWR<{
    invoices: Array<{
      id: string;
      supplier_gstin: string;
      supplier_name?: string | null;
      invoice_number: string;
      invoice_date: string | null;
      amount: number | null;
      decision_what: string;
      decision_why: string;
      decision_next: string;
      matched_pr_id?: string | null;
    }>;
    total: number;
  }>(duplicateEntryListKey, authJsonFetcher, { revalidateOnFocus: false });

  const sortedDuplicateEntries = useMemo(
    () =>
      sortDuplicateEntryRows(
        duplicateEntryData?.invoices ?? [],
        duplicateEntrySort
      ),
    [duplicateEntryData?.invoices, duplicateEntrySort]
  );

  const {
    data: unmatchedNotesData,
    error: unmatchedNotesError,
    isLoading: unmatchedNotesLoading,
  } = useSWR<{
    invoices: Array<{
      id: string;
      supplier_gstin: string;
      supplier_name?: string | null;
      invoice_number: string;
      invoice_date: string | null;
      amount: number | null;
      match_status?: string | null;
      decision_what: string;
      decision_why: string;
      decision_next: string;
    }>;
    total: number;
  }>(unmatchedNotesListKey, authJsonFetcher, { revalidateOnFocus: false });

  const lateMatchesKey = useMemo(
    () =>
      authReady &&
      runId &&
      resultsTab === "matched" &&
      summary &&
      typeof summary.late_match_count === "number" &&
      summary.late_match_count > 0
        ? ([`/api/reconcile/runs/${runId}/late-matches`, authToken] as const)
        : null,
    [authReady, runId, summary?.late_match_count, authToken, resultsTab]
  );

  const {
    data: lateMatchesData,
    error: lateMatchesError,
    isLoading: lateMatchesLoading,
  } = useSWR<{ data: LateMatchRow[]; total: number }>(
    lateMatchesKey,
    authJsonFetcher,
    { revalidateOnFocus: false }
  );

  const matchedQuery = useMemo(
    () =>
      buildMatchedQuery(
        matchedPage,
        matchedPageSize,
        debouncedMatchedSearch,
        matchedSort,
        matchedFilters
      ),
    [matchedPage, matchedPageSize, debouncedMatchedSearch, matchedSort, matchedFilters]
  );

  const matchedKey = useMemo(
    () =>
      authReady && runId && resultsTab === "matched"
        ? ([`/api/reconcile/runs/${runId}/matched?${matchedQuery}`, authToken] as const)
        : null,
    [authReady, runId, matchedQuery, authToken, resultsTab]
  );

  useEffect(() => {
    console.log(
      "[results] matchedKey:",
      matchedKey ? matchedKey[0] : "null (waiting for auth)"
    );
  }, [matchedKey]);

  const {
    data: matchedData,
    error: matchedError,
    isLoading: matchedLoading,
    mutate: mutateMatched,
  } = useSWR<Paginated<ReconcileRow>>(matchedKey, authJsonFetcher, {
    revalidateOnFocus: false,
    // isPaused removed: key is already null when auth isn't ready, so isPaused
    // is redundant. In SWR v2 the isPaused closure can capture a stale
    // authToken=null when the key transitions null→non-null, silently blocking
    // the fetch and leaving matchedData undefined forever.
  });

  // ─── Review Required tab ─────────────────────────────────────────────────
  const reviewRequiredQuery = useMemo(
    () =>
      buildMatchedQuery(
        reviewRequiredPage,
        reviewRequiredPageSize,
        debouncedReviewRequiredSearch,
        reviewRequiredSort,
        { ...reviewRequiredFilters, force_review_required: true }
      ),
    [
      reviewRequiredPage,
      reviewRequiredPageSize,
      debouncedReviewRequiredSearch,
      reviewRequiredSort,
      reviewRequiredFilters,
    ]
  );

  const reviewRequiredKey = useMemo(
    () =>
      authReady && runId && resultsTab === "review_required"
        ? ([`/api/reconcile/runs/${runId}/matched?${reviewRequiredQuery}`, authToken] as const)
        : null,
    [authReady, runId, reviewRequiredQuery, authToken, resultsTab]
  );

  const {
    data: reviewRequiredData,
    error: reviewRequiredError,
    isLoading: reviewRequiredLoading,
    mutate: mutateReviewRequired,
  } = useSWR<Paginated<ReconcileRow>>(reviewRequiredKey, authJsonFetcher, {
    revalidateOnFocus: false,
  });

  // Keys are null until the accordion is opened — this guarantees SWR
  // triggers a real fetch the moment the user expands the section.
  // Using isPaused() alone is unreliable in SWR v2: it does not re-trigger
  // a fetch when its return value changes from true→false.
  const rule37ListKey = useMemo(
    () =>
      authReady && runId && rule37Open
        ? ([
            `/api/reconcile/runs/${runId}/rule37?page=${rule37Page}&limit=${rule37PageSize}`,
            authToken,
          ] as const)
        : null,
    [authReady, runId, rule37Page, rule37PageSize, authToken, rule37Open]
  );

  const {
    data: rule37Data,
    error: rule37Error,
    isLoading: rule37Loading,
    mutate: mutateRule37,
  } = useSWR<Paginated<ReconcileRow>>(rule37ListKey, authJsonFetcher, {
    revalidateOnFocus: false,
  });

  const section17ListKey = useMemo(
    () =>
      authReady && runId && section17Open
        ? ([
            `/api/reconcile/runs/${runId}/section17?page=${section17Page}&limit=${section17PageSize}`,
            authToken,
          ] as const)
        : null,
    [authReady, runId, section17Page, section17PageSize, authToken, section17Open]
  );

  const {
    data: section17Data,
    error: section17Error,
    isLoading: section17Loading,
    mutate: mutateSection17,
  } = useSWR<Paginated<ReconcileRow>>(section17ListKey, authJsonFetcher, {
    revalidateOnFocus: false,
  });

  const einvoiceResKey = useMemo(
    () =>
      authReady && runId
        ? ([`/api/einvoice-recon/results/${runId}`, authToken] as const)
        : null,
    [authReady, runId, authToken]
  );

  const { data: einvoiceResData } = useSWR<{
    summary?: { total_records?: number };
  }>(einvoiceResKey, authJsonFetcher, {
    revalidateOnFocus: false,
  });

  const notesKey = useMemo(
    () =>
      authReady && activeRecord
        ? ([`/api/notes/${activeRecord.id}`, authToken] as const)
        : null,
    [authReady, activeRecord, authToken]
  );

  const {
    data: drawerNotes = [],
    isLoading: drawerNotesLoading,
    mutate: mutateDrawerNotes,
  } = useSWR<Note[]>(
    notesKey,
    async ([path, token]: FetcherKey) => {
      const rows = await apiFetch<Record<string, unknown>[]>(path, { token });
      return (rows ?? []).map(mapApiNote);
    },
    {
      revalidateOnFocus: false,
    }
  );

  const effectiveStatus = useCallback(
    (row: ReconcileRow): DecisionStatus =>
      localDecisionStatus.get(row.id) ?? row.decision_status,
    [localDecisionStatus]
  );

  const runBulkDecision = useCallback(
    async (
      section: "itc" | "risk",
      ids: string[],
      status: DecisionStatus,
      selectedSnapshot: Set<string>
    ) => {
      if (ids.length === 0 || !authToken) return;
      const t = authToken;
      let mapBefore = new Map<string, DecisionStatus>();
      setLocalDecisionStatus((prev) => {
        mapBefore = new Map(prev);
        const next = new Map(prev);
        for (const id of ids) next.set(id, status);
        return next;
      });
      setSelectedIds((prev) => {
        const next = { ...prev, [section]: new Set(prev[section]) };
        next[section].clear();
        return next;
      });
      try {
        await apiFetch<{ updated_count: number }>(
          "/api/reconcile/records/bulk-update",
          {
            method: "PATCH",
            token: t,
            body: JSON.stringify({
              run_id: runId,
              record_ids: ids,
              decision_status: status,
            }),
          }
        );
        if (section === "itc") await mutateItc();
        else await mutateRisk();
        addToast(`${ids.length} records updated`, "success");
        setLocalDecisionStatus((prev) => {
          const next = new Map(prev);
          for (const id of ids) next.delete(id);
          return next;
        });
      } catch {
        setLocalDecisionStatus((prev) => {
          const next = new Map(prev);
          for (const id of ids) {
            if (mapBefore.has(id)) next.set(id, mapBefore.get(id)!);
            else next.delete(id);
          }
          return next;
        });
        setSelectedIds((prev) => ({
          ...prev,
          [section]: new Set(selectedSnapshot),
        }));
        addToast("Update failed — changes reversed", "error");
      }
    },
    [addToast, authToken, mutateItc, mutateRisk, runId]
  );

  const runSingleDecision = useCallback(
    async (recordId: string, status: DecisionStatus) => {
      if (!authToken) return;
      setDrawerDecisionError(null);
      const t = authToken;
      setLocalDecisionStatus((prev) => {
        const next = new Map(prev);
        next.set(recordId, status);
        return next;
      });
      try {
        await apiFetch<{ updated_count: number }>(
          "/api/reconcile/records/bulk-update",
          {
            method: "PATCH",
            token: t,
            body: JSON.stringify({
              run_id: runId,
              record_ids: [recordId],
              decision_status: status,
            }),
          }
        );
        await Promise.all([
          mutateItc(),
          mutateRisk(),
          mutateMatched(),
          mutateRule37(),
          mutateSection17(),
        ]);
        setLocalDecisionStatus((prev) => {
          const next = new Map(prev);
          next.delete(recordId);
          return next;
        });
        setActiveRecord((cur) =>
          cur && cur.id === recordId
            ? { ...cur, decision_status: status }
            : cur
        );
      } catch {
        setLocalDecisionStatus((prev) => {
          const next = new Map(prev);
          next.delete(recordId);
          return next;
        });
        setDrawerDecisionError("Update failed — try again");
      }
    },
    [
      mutateItc,
      mutateMatched,
      mutateRisk,
      mutateRule37,
      mutateSection17,
      authToken,
      runId,
    ]
  );

  const submitNote = useCallback(async () => {
    const text = newNoteText.trim();
    if (!text || !activeRecord || !authToken || !runId) return;
    setNotePostError(null);
    setNotePosting(true);
    const tempId = `temp-${Date.now()}`;
    const optimistic: Note = {
      id: tempId,
      author_name: "You",
      created_at: new Date().toISOString(),
      note_text: text,
    };
    await mutateDrawerNotes((prev) => [optimistic, ...(prev ?? [])], {
      revalidate: false,
    });
    setNewNoteText("");
    try {
      const createdRaw = await apiFetch<Record<string, unknown>>(
        `/api/notes/${activeRecord.id}`,
        {
          method: "POST",
          token: authToken,
          body: JSON.stringify({
            note: text,
            run_id: runId,
            record_type: "matched",
          }),
        }
      );
      const created = mapApiNote(createdRaw);
      await mutateDrawerNotes(
        (prev) => (prev ?? []).map((n) => (n.id === tempId ? created : n)),
        { revalidate: false }
      );
      void mutateMatched();
    } catch {
      await mutateDrawerNotes(
        (prev) => (prev ?? []).filter((n) => n.id !== tempId),
        { revalidate: false }
      );
      setNotePostError("Failed — try again");
    } finally {
      setNotePosting(false);
    }
  }, [
    activeRecord,
    authToken,
    mutateDrawerNotes,
    mutateMatched,
    newNoteText,
    runId,
  ]);

  const itcHeaderRef = useRef<HTMLInputElement>(null);
  const riskHeaderRef = useRef<HTMLInputElement>(null);

  const itcRows = itcPageData?.data ?? [];
  const itcMax = useMemo(
    () => itcRows.reduce((m, r) => Math.max(m, r.amount), 0),
    [itcRows]
  );

  /** True when the loaded ITC rows contain at least one GSTR-2B-only credit or
   *  debit note.  Used to adjust section labels so the net figure is not
   *  presented as purely claimable ITC. */
  const itcHasCdnRows = useMemo(
    () =>
      itcRows.some((r) => {
        const dt =
          (r.gstr2b_data?.["doc_type"] as string | undefined) ??
          (r.gstr2b_data?.["document_type"] as string | undefined);
        return dt === "CREDIT_NOTE" || dt === "DEBIT_NOTE";
      }),
    [itcRows]
  );

  useEffect(() => {
    const el = itcHeaderRef.current;
    if (!el || !itcRows.length) return;
    const n = itcRows.filter((r) => selectedIds.itc.has(r.id)).length;
    el.indeterminate = n > 0 && n < itcRows.length;
  }, [selectedIds.itc, itcRows]);

  const riskRows = riskPageData?.data ?? [];
  const riskMax = useMemo(
    () => riskRows.reduce((m, r) => Math.max(m, r.amount), 0),
    [riskRows]
  );

  const topSuppliersByRisk = useMemo(() => {
    const grand = summary?.wrongful_risk_total_amount ?? 0;
    const sourceRows = riskGroupBySupplier ? (riskAllRows ?? []) : riskRows;
    if (!sourceRows.length) return [];
    const m = new Map<
      string,
      { gstin: string; tradeName: string; count: number; total: number }
    >();
    for (const row of sourceRows) {
      const g = row.supplier_gstin?.trim();
      if (!g) continue;
      const cur = m.get(g) ?? {
        gstin: g,
        tradeName: (row.trade_name && String(row.trade_name).trim()) || "",
        count: 0,
        total: 0,
      };
      if (!cur.tradeName && row.trade_name)
        cur.tradeName = String(row.trade_name).trim();
      cur.count += 1;
      cur.total += row.amount;
      m.set(g, cur);
    }
    return Array.from(m.values())
      .sort((a, b) => b.total - a.total)
      .slice(0, 5)
      .map((s) => ({
        ...s,
        impact: supplierRiskImpactLabel(s.total, grand),
      }));
  }, [
    riskRows,
    riskAllRows,
    riskGroupBySupplier,
    summary?.wrongful_risk_total_amount,
  ]);

  useEffect(() => {
    const el = riskHeaderRef.current;
    if (!el || !riskRows.length) return;
    const n = riskRows.filter((r) => selectedIds.risk.has(r.id)).length;
    el.indeterminate = n > 0 && n < riskRows.length;
  }, [selectedIds.risk, riskRows]);

  const riskRowsSelectedOnPage = useMemo(
    () => riskRows.filter((r) => selectedIds.risk.has(r.id)),
    [riskRows, selectedIds.risk]
  );

  const riskSelectionGstinCount = useMemo(() => {
    const set = new Set(
      riskRowsSelectedOnPage.map((r) =>
        (r.supplier_gstin || "").trim().toUpperCase()
      )
    );
    set.delete("");
    return set.size;
  }, [riskRowsSelectedOnPage]);

  const openFollowupLetter = useCallback((rows: ReconcileRow[]) => {
    if (!rows.length) return;
    const gstins = new Set(
      rows.map((r) => (r.supplier_gstin || "").trim().toUpperCase()).filter(Boolean)
    );
    if (gstins.size !== 1) {
      setFollowupSelectionHint(
        "Select invoices from one supplier only to generate a combined follow-up letter."
      );
      return;
    }
    setFollowupSelectionHint(null);
    setFollowupLetterRows(rows);
  }, []);

  const tryOpenBulkFollowup = useCallback(() => {
    const onPage = riskRowsSelectedOnPage;
    if (selectedIds.risk.size > onPage.length) {
      setFollowupSelectionHint(
        "Some selected invoices are on another page. Generate follow-up for rows on this page, or clear selection and re-select here."
      );
      return;
    }
    if (onPage.length === 0) {
      setFollowupSelectionHint("Select at least one invoice.");
      return;
    }
    openFollowupLetter(onPage);
  }, [
    riskRowsSelectedOnPage,
    selectedIds.risk.size,
    openFollowupLetter,
  ]);

  const rule37SummaryKey = useMemo(
    () =>
      authReady && runId
        ? ([`/api/reconcile/runs/${encodeURIComponent(runId)}/rule37/summary`, authToken, rule37SummaryRefreshKey] as const)
        : null,
    [authReady, runId, authToken, rule37SummaryRefreshKey]
  );
  const { data: rule37SummaryData } = useSWR(
    rule37SummaryKey,
    ([url, token]) => apiFetch<Rule37SummaryResponse>(url, { token: token ?? undefined }),
    { revalidateOnFocus: false }
  );

  const rule37TotalAmount = rule37SummaryData?.summary.total_itc_at_risk ?? null;
  const rule37HeaderSublabel = formatRule37HeaderCoverageSublabel(
    rule37SummaryData?.summary
  );

  const unresolvedRule37Count = useMemo(() => {
    const rows = rule37Data?.data ?? [];
    return rows.filter((row) => {
      const status =
        localRule37ActionStatus.get(row.id) ?? row.rule37_action_status;
      return status !== "resolved" && status !== "acknowledged" && status !== "rejected";
    }).length;
  }, [localRule37ActionStatus, rule37Data?.data]);

  const finalizeBarVisible =
    summary?.user_role === "admin" && !isRunFinalized;
  const staffFinalizeMessageVisible =
    summary?.user_role === "staff" && !isRunFinalized;
  const canDeleteRun = summary?.user_role === "admin";

  const authProfileKey = useMemo(
    () =>
      authReady && authToken
        ? (["results-me-recon", authToken] as const)
        : null,
    [authReady, authToken]
  );
  const { data: authProfile } = useSWR(
    authProfileKey,
    ([, t]) => authProfileFetcher(t),
    AUTH_PROFILE_SWR_OPTIONS
  );

  useEffect(() => {
    if (authProfile?.auto_approve_confidence_threshold != null) {
      setAutoApproveThreshold(authProfile.auto_approve_confidence_threshold);
    }
  }, [authProfile?.auto_approve_confidence_threshold]);

  const canEditAutoApproveThreshold =
    summary?.user_role === "admin" ||
    (authProfile?.role || "").toLowerCase() === "admin";

  const saveAutoApproveThreshold = useCallback(async () => {
    if (!authToken || !canEditAutoApproveThreshold) return;
    const clamped = Math.max(
      0,
      Math.min(100, Math.round(autoApproveThreshold))
    );
    setAutoApproveSaving(true);
    try {
      await reconcileSettingsApi.updateAutoApproveThreshold(authToken, clamped);
      setAutoApproveThreshold(clamped);
      addToast("Auto-approve threshold saved", "success");
      if (authProfileKey) void swrMutate(authProfileKey);
      void swrMutate(["settings-me", authToken]);
      void swrMutate(["settings-me-recon", authToken]);
    } catch (err) {
      addToast(
        isApiError(err) ? err.detail : "Failed to save threshold",
        "error"
      );
    } finally {
      setAutoApproveSaving(false);
    }
  }, [
    addToast,
    authProfileKey,
    authToken,
    autoApproveThreshold,
    canEditAutoApproveThreshold,
  ]);

  const exportScopeLabel = (
    <p className="text-[11px] text-gray-500">
      Full workbook · all sections
    </p>
  );

  const closeFinalizeModal = useCallback(() => {
    if (finalizing) return;
    setFinalizeModalOpen(false);
    setChecklist({ ...EMPTY_FINALIZE_CHECKLIST });
  }, [finalizing]);

  const closeDeleteModal = useCallback(() => {
    if (deleting) return;
    setDeleteModalOpen(false);
    setDeleteError(null);
  }, [deleting]);

  const actOnRule37 = useCallback(
    async (
      recordId: string,
      status: Rule37ActionStatus,
      payment?: {
        amount_paid: number;
        tds_deducted: number;
        tds_confirmed: boolean;
      }
    ) => {
      if (!runId || !authToken || rule37UpdatingIds.has(recordId)) return;
      setRule37UpdatingIds((prev) => {
        const next = new Set(prev);
        next.add(recordId);
        return next;
      });
      try {
        const body =
          status === "resolved" && payment
            ? { status, ...payment }
            : { status };
        const res = await apiFetch<{
          id: string;
          status: Rule37ActionStatus;
          acted_by: string;
          acted_at: string;
          payment_coverage?: "full" | "partial" | null;
        }>(`/api/reconcile/runs/${runId}/rule37/${encodeURIComponent(recordId)}`, {
          method: "PATCH",
          token: authToken,
          body: JSON.stringify(body),
        });
        setLocalRule37ActionStatus((prev) => {
          const next = new Map(prev);
          next.set(recordId, status);
          return next;
        });
        await mutateRule37((current) => {
          if (!current) return current;
          return {
            ...current,
            data: current.data.map((row) =>
              row.id === recordId
                ? {
                    ...row,
                    rule37_action_status: status,
                    rule37_payment_coverage:
                      res.payment_coverage ?? row.rule37_payment_coverage,
                  }
                : row
            ),
          };
        }, { revalidate: false });
        setRule37SummaryRefreshKey((k) => k + 1);
        if (status === "resolved") {
          setRule37MarkPaidTarget(null);
          addToast(
            res.payment_coverage === "partial"
              ? "Rule 37 marked as settled (partial payment)"
              : "Rule 37 marked as settled",
            "success"
          );
        } else {
          addToast("Rule 37 ITC reversal noted", "success");
        }
      } catch (e: unknown) {
        let msg = "Failed to update Rule 37 status";
        if (
          e &&
          typeof e === "object" &&
          "detail" in e &&
          typeof (e as { detail: unknown }).detail === "string"
        ) {
          msg = (e as { detail: string }).detail;
        }
        addToast(msg, "error");
      } finally {
        setRule37UpdatingIds((prev) => {
          const next = new Set(prev);
          next.delete(recordId);
          return next;
        });
      }
    },
    [addToast, authToken, mutateRule37, rule37UpdatingIds, runId]
  );

  const submitDeleteRun = useCallback(async () => {
    if (!runId || !authToken || deleting || !canDeleteRun) return;
    setDeleting(true);
    setDeleteError(null);
    try {
      await apiFetch<{ message: string }>(
        `/api/reconcile/runs/${runId}`,
        {
          method: "DELETE",
          token: authToken,
        }
      );
      router.push("/dashboard");
    } catch (e: unknown) {
      setDeleting(false);
      let msg = "Failed to delete run — try again";
      if (
        e &&
        typeof e === "object" &&
        "detail" in e &&
        typeof (e as { detail: unknown }).detail === "string"
      ) {
        msg = (e as { detail: string }).detail;
      }
      setDeleteError(msg);
    }
  }, [authToken, canDeleteRun, deleting, runId, router]);

  const submitFinalize = useCallback(async () => {
    if (!runId || !authToken) return;
    const checkedCount = Object.values(checklist).filter(Boolean).length;
    if (checkedCount !== 5 || finalizing) return;
    setFinalizing(true);
    try {
      const updated = await apiFetch<RunSummary>(
        `/api/reconcile/runs/${runId}/finalize`,
        {
          method: "POST",
          token: authToken,
          body: JSON.stringify({ checklist_snapshot: checklist }),
        }
      );
      await mutateSummary(updated, { revalidate: false });
      await Promise.all([
        mutateItc(),
        mutateRisk(),
        mutateMatched(),
        mutateRule37(),
        mutateSection17(),
      ]);
      setFinalizeModalOpen(false);
      setChecklist({ ...EMPTY_FINALIZE_CHECKLIST });
      setFinalizing(false);
      addToast("Reconciliation finalized successfully", "success");
    } catch (e: unknown) {
      setFinalizing(false);
      let msg = "Finalization failed — try again";
      if (
        e &&
        typeof e === "object" &&
        "detail" in e &&
        typeof (e as { detail: unknown }).detail === "string"
      ) {
        msg = (e as { detail: string }).detail;
      }
      addToast(msg, "error");
    }
  }, [
    addToast,
    checklist,
    finalizing,
    mutateItc,
    mutateMatched,
    mutateRisk,
    mutateRule37,
    mutateSection17,
    mutateSummary,
    runId,
    authToken,
  ]);

  if (tokenState === null) {
    return (
      <div className="flex min-h-[40vh] items-center justify-center text-gray-500">
        Loading session…
      </div>
    );
  }

  if (tokenState === false) {
    return (
      <div className="p-8 text-center text-gray-600">
        Sign in required to view reconciliation results.
      </div>
    );
  }

  if (!runId) {
    return <div className="p-8 text-gray-600">Invalid run.</div>;
  }

  const runStatus = (summary?.status ?? "").toUpperCase();
  const isProcessing = [
    "PROCESSING",
    "PENDING",
    "RUNNING",
    "MATCHING",
    "IMPORTING",
    "UPLOADING",
    "READY",
    "GSTR_IMPORT_COMPLETE",
    "PURCHASE_IMPORT_COMPLETE",
  ].includes(runStatus);
  const isRunFailed = runStatus === "FAILED";
  const runFailMsg = summary?.status_message?.trim()
    ? `This run failed: ${summary.status_message.trim()}`
    : "This run failed.";
  const sectionLoadError = (fallback: string) =>
    isRunFailed ? runFailMsg : fallback;

  if (isProcessing) {
    return (
      <div className="box-border -mx-8 -mt-8 flex min-h-[60vh] flex-col items-center justify-center px-8">
        <Loader2 className="mb-4 h-10 w-10 animate-spin text-[var(--ink)]" />
        <p className="text-base font-medium text-[var(--ink)]">
          {summary?.status_message?.trim() ||
            "Running reconciliation... This usually takes 20–40 seconds."}
        </p>
      </div>
    );
  }

  if (isRunFailed && summary && !summaryError) {
    return (
      <div className="box-border -mx-8 -mt-8 min-h-screen min-w-0 w-[calc(100%+4rem)] max-w-[calc(100%+4rem)] overflow-x-hidden px-8 py-10">
        <SectionError
          message={runFailMsg}
          onRetry={() => void mutateSummary()}
        />
      </div>
    );
  }

  return (
    <div className="box-border min-h-screen min-w-0 w-full space-y-3 pb-28">
      {/* Context bar */}
      <div
        ref={summaryRef}
        className="box-border w-full min-w-0 rounded-[10px] border border-[#E2E8F0] bg-white px-6 py-3.5 shadow-sm"
      >
        {/* Show skeleton while auth is initialising OR the fetch is in-flight */}
        {(authLoading || summaryLoading) && <SummarySkeleton />}
        {!authLoading && !summaryLoading && summaryError && (
          <SectionError
            message={
              isRunFailed
                ? runFailMsg
                : "Failed to load summary."
            }
            onRetry={() => void mutateSummary()}
          />
        )}
        {/* Auth resolved with a token but summary not yet populated — brief
            retry window; only shown when we are actually authenticated. */}
        {!authLoading && !summaryLoading && !summaryError && !summary && authReady && (
          <SummarySkeleton />
        )}
        {summary && !summaryError && (
          <div className="flex w-full flex-wrap items-center justify-between gap-3">
            <div className="flex min-w-0 flex-wrap items-center gap-2.5">
              <div className="flex min-w-0 items-center gap-1.5 text-xs text-[#94A3B8]">
                <Link href="/clients" className="shrink-0 hover:text-[#0F172A] transition-colors">
                  Clients
                </Link>
                <span className="shrink-0 text-[#CBD5E1]">›</span>
                <span className="truncate font-semibold text-[#0F172A] max-w-[200px] sm:max-w-xs" title={summary.client_name ?? undefined}>
                  {summary.client_name || "—"}
                </span>
                <span className="shrink-0 text-[#CBD5E1]">›</span>
                <span className="shrink-0 font-medium text-[#475569]">
                  {formatPeriod(summary.period)}
                </span>
              </div>
              {(summary.client_gstin || summary.client_gstin_id) && (
                <span className="shrink-0 rounded border border-[#E2E8F0] bg-[#F8FAFC] px-2 py-0.5 font-mono text-[11px] tracking-wide text-[#94A3B8]">
                  {summary.client_gstin || summary.client_gstin_id}
                </span>
              )}
            </div>

            <div className="flex shrink-0 items-center gap-2">
              <button
                type="button"
                disabled={excelDownloading}
                className="inline-flex items-center gap-1.5 rounded-md border border-[#E2E8F0] bg-white px-3 py-1.5 text-xs font-medium text-[#475569] transition-colors hover:bg-[#F8FAFC] disabled:cursor-not-allowed disabled:opacity-50"
                onClick={() => void downloadExcelReport()}
              >
                {excelDownloading ? (
                  <Loader2 className="h-3 w-3 animate-spin text-gray-400" />
                ) : (
                  <svg width="12" height="12" viewBox="0 0 12 12" fill="none" stroke="currentColor" strokeWidth="1.5">
                    <path d="M2 9h8M6 1v6M3 4l3-3 3 3" />
                  </svg>
                )}
                Export
              </button>
              <button
                type="button"
                disabled={pdfDownloading}
                className="inline-flex items-center gap-1.5 rounded-md border border-[#E2E8F0] bg-white px-3 py-1.5 text-xs font-medium text-[#475569] transition-colors hover:bg-[#F8FAFC] disabled:cursor-not-allowed disabled:opacity-50"
                onClick={() => void downloadPdfReport()}
              >
                {pdfDownloading ? (
                  <Loader2 className="h-3 w-3 animate-spin text-gray-400" />
                ) : (
                  <svg width="12" height="12" viewBox="0 0 12 12" fill="none" stroke="currentColor" strokeWidth="1.5">
                    <path d="M2 2h8v8H2z" />
                    <path d="M4 5h4M4 7h2" />
                  </svg>
                )}
                PDF Report
              </button>
              {canDeleteRun && (
                <button
                  type="button"
                  className="inline-flex items-center gap-1.5 rounded-md border border-red-200 bg-white px-2 py-1.5 text-xs text-red-600 hover:bg-red-50"
                  title="Delete run"
                  onClick={() => {
                    setDeleteError(null);
                    setDeleteModalOpen(true);
                  }}
                >
                  <Trash2 className="h-3.5 w-3.5 shrink-0" />
                </button>
              )}
              {!isRunFinalized ? (
                <button
                  type="button"
                  className="rounded-md bg-[#DC2626] px-3.5 py-1.5 text-xs font-medium text-white transition-colors hover:bg-red-700 whitespace-nowrap"
                  onClick={() => setFinalizeModalOpen(true)}
                >
                  Finalize Run
                </button>
              ) : (
                <span className="rounded-md bg-emerald-100 px-3 py-1.5 text-xs font-medium text-emerald-800 whitespace-nowrap">
                  Finalized
                </span>
              )}
            </div>
          </div>
        )}
      </div>

      <div className={pageContentClass}>
        {summary && (summary.isd_count ?? 0) > 0 && (
          <div
            className="rounded-[10px] border border-amber-300 bg-amber-50 px-4 py-2.5 text-xs text-amber-950"
            role="alert"
          >
            <strong>ISD / Import of goods:</strong>{" "}
            {summary.isd_impg_warning?.trim() ||
              `This GSTR-2B file contains ${(summary.isd_count ?? 0) > 0 ? `${summary.isd_count!.toLocaleString("en-IN")} ISD credit line(s)` : ""} not included in reconciliation.`}
          </div>
        )}

        {summary && (summary.unmatched_notes_count ?? 0) > 0 && (
          <div
            className="flex items-center justify-between rounded-[10px] border border-amber-300 bg-amber-50 px-4 py-2.5 text-xs text-amber-950"
            role="alert"
          >
            <span>
              {(summary.unmatched_notes_count ?? 0).toLocaleString("en-IN")} credit/debit notes were excluded from invoice matching.
            </span>
            <button
              type="button"
              className="ml-2 font-semibold underline hover:text-amber-900"
              onClick={() => setResultsTab("unmatched_notes")}
            >
              View notes
            </button>
          </div>
        )}

        {summary && (summary.pr_skipped_count ?? 0) > 0 && (
          <div
            className="rounded-[10px] bg-amber-50 px-4 py-2 text-xs text-amber-950"
            role="status"
          >
            {summary.pr_skipped_detail?.trim() ||
              `${summary.pr_skipped_count!.toLocaleString("en-IN")} purchase register rows skipped (missing invoice number).`}
          </div>
        )}

        {/* KPI section */}
        {summary && !summaryError && (
          <div className="grid grid-cols-1 gap-3 lg:grid-cols-2">
            {/* Left: Run summary */}
            <div className="flex items-center gap-6 rounded-[10px] border border-[#E2E8F0] bg-white p-5 px-6">
              <div className="min-w-[84px] text-center">
                <div className="mb-1 text-xs font-semibold uppercase tracking-wider text-[#94A3B8]">
                  {tResults("runTotal")}
                </div>
                <div className="text-[36px] font-black leading-none text-[#0F172A]">
                  {summary.total_gstr_records.toLocaleString("en-IN")}
                </div>
                <div className="mt-1.5 text-xs font-medium text-[#94A3B8]">{tResults("invoices")}</div>
              </div>
              <div className="h-14 w-[1px] bg-[#F1F5F9]" />
              <div className="flex-1">
                <div className="mb-1.5 flex justify-between text-xs text-[#94A3B8]">
                  <span className="font-semibold uppercase tracking-wider">{tResults("matched")}</span>
                  <span className="text-base sm:text-lg font-bold text-[#16A34A]">
                    {(summary.clean_matched_count ?? summary.matched_count).toLocaleString("en-IN")} · {Math.round(((summary.clean_matched_count ?? summary.matched_count) / Math.max(summary.total_gstr_records, 1)) * 100)}%
                  </span>
                </div>
                <div className="h-2 w-full overflow-hidden rounded-full bg-[#F1F5F9]">
                  <div
                    className="h-full rounded-full bg-[#16A34A] transition-all duration-150"
                    style={{
                      width: `${Math.min(100, Math.max(0, Math.round(((summary.clean_matched_count ?? summary.matched_count) / Math.max(summary.total_gstr_records, 1)) * 100)))}%`,
                    }}
                  />
                </div>
                <div className="mt-1.5 text-xs font-medium text-[#64748B]">
                  {summary.total_gstr_records - (summary.clean_matched_count ?? summary.matched_count) > 0
                    ? `${(summary.total_gstr_records - (summary.clean_matched_count ?? summary.matched_count)).toLocaleString("en-IN")} ${tResults("invoicesNeedAttention")}`
                    : tResults("allInvoicesCleanMatched")}
                </div>
              </div>
              <div className="h-14 w-[1px] bg-[#F1F5F9]" />
              <div className="min-w-[76px] text-center">
                <div className="mb-1 text-xs font-semibold uppercase tracking-wider text-[#94A3B8]">
                  {tResults("assigned")}
                </div>
                <div className="mt-1 text-sm font-bold text-[#0F172A]">
                  {summary.assigned_to_name?.trim() ? summary.assigned_to_name : tResults("unassigned")}
                </div>
                <div className="mt-1 text-xs text-[#94A3B8]">
                  {formatPeriod(summary.period)}
                </div>
              </div>
            </div>

            {/* Right: Action required */}
            <div className="overflow-hidden rounded-[10px] border border-[#E2E8F0] bg-white">
              <div className="flex items-center gap-2 border-b border-[#FEF2F2] bg-[#FFF7F7] px-6 py-3">
                <div className="h-2 w-2 rounded-full bg-[#DC2626]" />
                <div className="text-xs sm:text-[13px] font-bold uppercase tracking-wider text-[#991B1B]">
                  {((summary.review_required_count ?? 0) + (summary.missed_itc_count ?? 0) + (summary.wrongful_risk_count ?? 0)).toLocaleString("en-IN")} {tResults("invoicesNeedAction")}
                </div>
              </div>
              <div
                className="flex cursor-pointer items-center border-b border-[#F8FAFC] px-6 py-3.5 transition-colors hover:bg-[#FAFAFA]"
                onClick={() => setResultsTab("review_required")}
              >
                <div className="flex-1 text-[13px] sm:text-sm font-medium text-[#334155]">{tResults("reviewRequired")}</div>
                <span className="rounded-[5px] border border-[#FCD34D] bg-[#FFFBEB] px-2 py-0.5 text-xs font-bold text-[#92400E]">
                  {(summary.review_required_count ?? 0).toLocaleString("en-IN")}
                </span>
                <div className="ml-2 text-base font-bold text-[#CBD5E1]">›</div>
              </div>
              <div
                className="flex cursor-pointer items-center border-b border-[#F8FAFC] px-6 py-3.5 transition-colors hover:bg-[#FAFAFA]"
                onClick={() => setResultsTab("itc")}
              >
                <div className="flex-1 text-[13px] sm:text-sm font-medium text-[#334155]">
                  {itcHasCdnRows ? tResults("net2bDifference") : tResults("missedItc")}
                </div>
                <span className="rounded-[5px] border border-[#FECACA] bg-[#FEF2F2] px-2 py-0.5 text-xs font-bold text-[#991B1B]">
                  {(summary.missed_itc_count ?? 0).toLocaleString("en-IN")}
                </span>
                <div className="ml-3 text-sm sm:text-[15px] font-black text-[#DC2626]">
                  {formatInrCompact(summary.missed_itc_total_amount)}
                </div>
                <div className="ml-2 text-base font-bold text-[#CBD5E1]">›</div>
              </div>
              <div
                className="flex cursor-pointer items-center px-6 py-3.5 transition-colors hover:bg-[#FAFAFA]"
                onClick={() => setResultsTab("risk")}
              >
                <div className="flex-1 text-[13px] sm:text-sm font-medium text-[#334155]">{tResults("itcAtRisk")}</div>
                <span className="rounded-[5px] border border-[#FECACA] bg-[#FEF2F2] px-2 py-0.5 text-xs font-bold text-[#991B1B]">
                  {(summary.wrongful_risk_count ?? 0).toLocaleString("en-IN")}
                </span>
                <div className="ml-3 text-sm sm:text-[15px] font-black text-[#DC2626]">
                  {formatInrCompact(summary.wrongful_risk_total_amount)}
                </div>
                <div className="ml-2 text-base font-bold text-[#CBD5E1]">›</div>
              </div>
            </div>
          </div>
        )}

        {/* Tabs & Table Card Wrapper */}
        <div className="overflow-hidden rounded-[10px] border border-[#E2E8F0] bg-white">
          {summary && (
            <ResultsBucketTabs
              active={resultsTab}
              onChange={setResultsTab}
              tabCounts={{
                matched: summary.clean_matched_count ?? summary.matched_count,
                review_required: summary.review_required_count ?? 0,
                duplicate_entry: summary.duplicate_entry_count ?? 0,
                unmatched_notes: summary.unmatched_notes_count ?? 0,
                risk: summary.wrongful_risk_count ?? 0,
                itc: summary.missed_itc_count ?? 0,
                ...(section17Data != null
                  ? { section17: section17Data.total }
                  : {}),
                ...(rule37Data != null ? { rule37: rule37Data.total } : {}),
                ...(einvoiceResData?.summary != null
                  ? { einvoice: einvoiceResData.summary.total_records }
                  : {}),
              }}
            />
          )}

        {/* ITC */}
        {resultsTab === "itc" &&
          summary &&
          summary.missed_itc_count === 0 &&
          summary.wrongful_risk_count === 0 && (
          <div className={sectionContainerClass}>
            <div className="flex gap-3">
              <Check className="mt-0.5 h-5 w-5 shrink-0 text-[#16A34A]" />
              <div>
                <h2 className="text-lg font-semibold text-gray-900">Perfect match!</h2>
                <p className="mt-1 text-[13px] text-gray-600">
                  No ITC missed this month. Every invoice in GSTR-2B is recorded in
                  your purchase register.
                </p>
              </div>
            </div>
          </div>
        )}

        {resultsTab === "itc" && summary && summary.missed_itc_count > 0 && (
          <div className={sectionContainerClass}>
            <SectionHeader
              title={
                itcHasCdnRows
                  ? "Net 2B Documents Not Booked in PR"
                  : "ITC You Can Still Claim"
              }
              dotColor="#16A34A"
              amount={summary.missed_itc_total_amount}
              amountLabel={
                itcHasCdnRows ? "NET 2B DIFFERENCE" : "TOTAL RECOVERABLE"
              }
              actions={
                <button
                  type="button"
                  disabled={itcCsvDownloading}
                  className={csvDownloadBtnClass}
                  onClick={() => void downloadItcCsv()}
                >
                  {itcCsvDownloading ? (
                    <Loader2 className="h-4 w-4 shrink-0 animate-spin text-gray-400" />
                  ) : null}
                  Download CSV
                </button>
              }
            />

            {/* Helper note: shown only when credit/debit notes are in the ITC bucket */}
            {itcHasCdnRows && (
              <div className="mb-5 flex items-start gap-2 rounded-xl border border-amber-200 bg-amber-50 px-4 py-3 text-[13px] text-amber-800">
                <svg
                  className="mt-0.5 h-4 w-4 shrink-0 text-amber-500"
                  viewBox="0 0 20 20"
                  fill="currentColor"
                  aria-hidden
                >
                  <path
                    fillRule="evenodd"
                    d="M8.485 2.495c.673-1.167 2.357-1.167 3.03 0l6.28 10.875c.673 1.167-.17 2.625-1.516 2.625H3.72c-1.347 0-2.189-1.458-1.515-2.625L8.485 2.495zM10 5a.75.75 0 01.75.75v3.5a.75.75 0 01-1.5 0v-3.5A.75.75 0 0110 5zm0 9a1 1 0 100-2 1 1 0 000 2z"
                    clipRule="evenodd"
                  />
                </svg>
                <span>
                  This amount is net of GSTR-2B-only debit notes and credit
                  notes.{" "}
                  <strong>Credit notes reduce ITC; debit notes increase the
                  difference.</strong>{" "}Some rows may not be directly claimable
                  — review each entry before filing.
                </span>
              </div>
            )}

            <div className={`${filterToolbarClass}`}>
              <div className={`${filterRowClass}`}>
                <input
                  type="text"
                  className={filterGstinInputClass}
                  placeholder="Filter by GSTIN..."
                  value={itcFilters.supplier_gstin}
                  onChange={(e) =>
                    setItcFilters((f) => ({
                      ...f,
                      supplier_gstin: e.target.value,
                    }))
                  }
                />
              </div>
              <div className={`${filterRowClass}`}>
                <input
                  type="text"
                  inputMode="decimal"
                  className={filterAmountInputClass}
                  placeholder="₹ Min"
                  value={itcFilters.amount_min}
                  onChange={(e) =>
                    setItcFilters((f) => ({ ...f, amount_min: e.target.value }))
                  }
                />
                <input
                  type="text"
                  inputMode="decimal"
                  className={filterAmountInputClass}
                  placeholder="₹ Max"
                  value={itcFilters.amount_max}
                  onChange={(e) =>
                    setItcFilters((f) => ({ ...f, amount_max: e.target.value }))
                  }
                />
                <input
                  type="date"
                  className={filterDateInputClass}
                  value={itcFilters.date_from}
                  onChange={(e) =>
                    setItcFilters((f) => ({ ...f, date_from: e.target.value }))
                  }
                />
                <input
                  type="date"
                  className={filterDateInputClass}
                  value={itcFilters.date_to}
                  onChange={(e) =>
                    setItcFilters((f) => ({ ...f, date_to: e.target.value }))
                  }
                />
                <select
                  className={filterDropdownClass}
                  value={itcFilters.ims_status}
                  onChange={(e) =>
                    setItcFilters((f) => ({ ...f, ims_status: e.target.value }))
                  }
                >
                  <option value="">All IMS</option>
                  <option value="accepted">IMS Accepted</option>
                  <option value="rejected">IMS Rejected</option>
                  <option value="pending">IMS Pending</option>
                  <option value="no_action_taken">IMS No action</option>
                </select>
                <select
                  className={filterSortDropdownClass}
                  aria-label="Sort by"
                  value={itcSort}
                  onChange={(e) =>
                    setItcSort(e.target.value as ReconcileSortValue)
                  }
                >
                  {RECONCILE_SORT_OPTIONS_BASE.map((opt) => (
                    <option key={opt.value} value={opt.value}>
                      {opt.label}
                    </option>
                  ))}
                </select>
                <button
                  type="button"
                  className={`${filterToggleClass} ${
                    itcGroupBySupplier
                      ? filterToggleActiveClass
                      : filterToggleIdleClass
                  }`}
                  onClick={() => {
                    setItcGroupBySupplier((on) => {
                      if (on) setItcExpandedSupplier(null);
                      return !on;
                    });
                  }}
                >
                  Group by Supplier
                </button>
                {(hasActiveItcFilters(itcFilters) || !!docTypeFilterItc) && (
                  <button
                    type="button"
                    className="h-9 text-[13px] font-medium text-[var(--ink)] hover:underline"
                    onClick={() => {
                      setDocTypeFilterItc("");
                      setItcFilters({
                        amount_min: "",
                        amount_max: "",
                        supplier_gstin: "",
                        date_from: "",
                        date_to: "",
                        ims_status: "",
                      });
                    }}
                  >
                    Clear filters
                  </button>
                )}
              </div>
            </div>

            {itcGroupBySupplier ? (
              <>
                {(itcAllRowsError || (itcError && !itcAllRows)) && (
                  <SectionError
                    message={sectionLoadError("Failed to load.")}
                    onRetry={() => void mutateItcAllRows()}
                  />
                )}
                {!itcAllRowsError && (
                  <SupplierGroupView<ReconcileRow>
                    groups={itcSupplierGroups}
                    expandedGstin={itcExpandedSupplier}
                    onToggleExpand={(gstin) =>
                      setItcExpandedSupplier((prev) =>
                        prev === gstin ? null : gstin
                      )
                    }
                    amountLabel="Missed ITC"
                    grandTotal={summary.missed_itc_total_amount}
                    loading={itcAllRowsLoading && !itcAllRows}
                    renderInvoices={(invoices) => (
                      <div className={decisionTableWrapClass}>
                        <table className={decisionTableClass}>
                          <thead className={tableHeadClass}>
                            <tr>
                              <th className={decisionTh("invoice")}>Invoice#</th>
                              <th className={decisionTh("date")}>Date</th>
                              <th className={decisionTh("amount", "right")}>
                                Amount
                              </th>
                              <th className={decisionTh("impact")}>Impact</th>
                              <th className={decisionTh("what")}>WHAT</th>
                              <th className={decisionTh("status")}>Status</th>
                              <th className={decisionTh("status")}>IMS</th>
                            </tr>
                          </thead>
                          <tbody>
                            {invoices.map((row) => (
                              <tr key={row.id} className={tableRowClass}>
                                <td className={decisionTd("invoice")}>
                                  <HoverTextCell
                                    text={row.invoice_number}
                                    displayClassName="text-[13px] font-medium text-gray-800"
                                  />
                                </td>
                                <td
                                  className={`${decisionTd("date")} text-[13px] text-gray-500`}
                                >
                                  {formatDate(row.invoice_date)}
                                </td>
                                <td className={decisionTd("amount")}>
                                  <AmountDisplay amount={row.amount} />
                                </td>
                                <td className={decisionTd("impact")}>
                                  <ImpactBadge
                                    level={getImpactLevel(
                                      row.amount,
                                      summary.missed_itc_total_amount
                                    )}
                                  />
                                </td>
                                <td className={decisionTd("what")}>
                                  <HoverTextCell
                                    text={row.decision_what}
                                    displayClassName="text-[13px] text-gray-600"
                                  />
                                </td>
                                <td className={decisionTd("status")}>
                                  <DecisionStatusPill
                                    status={effectiveStatus(row)}
                                  />
                                </td>
                                <td className={decisionTd("status")}>
                                  <ImsStatusBadge status={row.ims_status} />
                                </td>
                              </tr>
                            ))}
                          </tbody>
                        </table>
                      </div>
                    )}
                  />
                )}
              </>
            ) : (
              <>
            {itcError && (
              <SectionError
                message={sectionLoadError("Failed to load.")}
                onRetry={() => void mutateItc()}
              />
            )}
            {itcLoading && !itcPageData && !itcError && (
              <div className={decisionTableWrapClass}>
                <table className={decisionTableClass}>
                  <DecisionTableColGroup />
                  <thead className={tableHeadClass}>
                    <tr>
                      {Array.from({ length: 11 }).map((_, i) => (
                        <th key={i} className="px-2 py-2">
                          <div className="h-4 w-14 max-w-full animate-pulse rounded bg-gray-200" />
                        </th>
                      ))}
                    </tr>
                  </thead>
                  <tbody>
                    {Array.from({ length: 8 }).map((_, r) => (
                      <tr key={r} className="border-b border-gray-100">
                        {Array.from({ length: 11 }).map((_, c) => (
                          <td key={c} className="px-2 py-2">
                            <div
                              className={`h-4 max-w-full animate-pulse rounded bg-gray-200 ${
                                c === 0
                                  ? "w-4"
                                  : c === 5
                                    ? "ml-auto w-20"
                                    : "w-28"
                              }`}
                            />
                          </td>
                        ))}
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
            {itcPageData && !itcError && (
              <>
                {selectedIds.itc.size > 0 && (
                  <div className="mb-3 flex flex-wrap items-center gap-3 rounded-xl border border-[#F0F0F0] bg-[#FAFAFA] px-4 py-2.5 text-[13px]">
                    <span className="text-gray-600">{selectedIds.itc.size} selected</span>
                    <button
                      type="button"
                      disabled={isRunFinalized}
                      className="rounded-lg border border-[#E5E7EB] bg-white px-3 py-1.5 text-[13px] font-medium text-gray-700 hover:bg-gray-50 disabled:cursor-not-allowed disabled:opacity-50"
                      onClick={() => {
                        const snap = new Set(selectedIds.itc);
                        const ids = Array.from(snap);
                        void runBulkDecision("itc", ids, "acted", snap);
                      }}
                    >
                      Mark as Acted
                    </button>
                    <button
                      type="button"
                      disabled={isRunFinalized}
                      className="rounded-lg border border-[#E5E7EB] bg-white px-3 py-1.5 text-[13px] font-medium text-gray-700 hover:bg-gray-50 disabled:cursor-not-allowed disabled:opacity-50"
                      onClick={() => {
                        const snap = new Set(selectedIds.itc);
                        const ids = Array.from(snap);
                        void runBulkDecision("itc", ids, "ignored", snap);
                      }}
                    >
                      Mark as Ignored
                    </button>
                    <button
                      type="button"
                      className="text-[13px] font-medium text-[var(--ink)] hover:underline"
                      onClick={() =>
                        setSelectedIds((p) => ({ ...p, itc: new Set() }))
                      }
                    >
                      Clear
                    </button>
                  </div>
                )}
                {itcPageData.data.length === 0 ? (
                  <EmptyTableState
                    title="No missed ITC rows for this filter"
                    description="Adjust amount, GSTIN, or date filters to see recoverable invoices."
                  />
                ) : (
                <DecisionInvoiceList
                  selectAll={
                    <>
                      <input
                        ref={itcHeaderRef}
                        type="checkbox"
                        disabled={isRunFinalized}
                        checked={
                          itcRows.length > 0 &&
                          itcRows.every((r) => selectedIds.itc.has(r.id))
                        }
                        onChange={(e) => {
                          const on = e.target.checked;
                          setSelectedIds((prev) => {
                            const next = {
                              ...prev,
                              itc: new Set(prev.itc),
                            };
                            if (on) itcRows.forEach((r) => next.itc.add(r.id));
                            else itcRows.forEach((r) => next.itc.delete(r.id));
                            return next;
                          });
                        }}
                        className="rounded border-gray-300"
                      />
                      <span className="text-[13px] font-medium text-gray-600">
                        Select all on this page
                      </span>
                    </>
                  }
                >
                  {itcRows.filter((r) => checkDocType(r, docTypeFilterItc)).map((row, i) => (
                    <DecisionInvoiceCard
                      key={row.id}
                      index={(itcPage - 1) * itcPageData.limit + i + 1}
                      gstin={row.supplier_gstin}
                      invoiceNumber={row.invoice_number}
                      invoiceDate={formatDate(row.invoice_date)}
                      amount={row.amount}
                      selected={selectedIds.itc.has(row.id)}
                      checkboxDisabled={isRunFinalized}
                      onSelectChange={(checked) => {
                        setSelectedIds((prev) => {
                          const next = { ...prev, itc: new Set(prev.itc) };
                          if (checked) next.itc.add(row.id);
                          else next.itc.delete(row.id);
                          return next;
                        });
                      }}
                      impact={
                        <ImpactBadge level={getImpactLevel(row.amount, itcMax)} />
                      }
                      status={
                        <div className="flex flex-wrap items-center gap-2">
                          <DecisionStatusPill status={effectiveStatus(row)} />
                          {effectiveStatus(row) === "pending" ? (
                            <span className="text-[11px] font-medium text-gray-500">
                              {row.discrepancy_note || "Review required"}
                            </span>
                          ) : null}
                          <ImsStatusBadge status={row.ims_status} />
                        </div>
                      }
                      meta={
                        <div className="flex flex-wrap items-center gap-1.5">
                          {row.match_confidence != null ? (
                            <MatchConfidenceBadge
                              score={row.match_confidence}
                              onClick={(e) => toggleRationale(e, row.id)}
                            />
                          ) : null}
                          {(row.compared_fields?.length ?? 0) > 0 ? (
                            <WhyRationaleButton
                              expanded={rationaleExpandedId === row.id}
                              onToggle={(e) => toggleRationale(e, row.id)}
                            />
                          ) : null}
                        </div>
                      }
                      what={row.decision_what}
                      why={row.decision_why}
                      next={row.decision_next}
                      expandedContent={
                        rationaleExpandedId === row.id ? (
                          <ComparedFieldsPanel row={row} />
                        ) : null
                      }
                    />
                  ))}
                </DecisionInvoiceList>
                )}
                {itcPageData.data.length > 0 && (
                <ReconcilePaginationFooter
                  page={itcPageData.page}
                  totalPages={itcPageData.total_pages}
                  total={itcPageData.total}
                  limit={itcPageData.limit}
                  pageSizeOptions={RECONCILE_TABLE_PAGE_SIZE_OPTIONS}
                  pageSize={itcPageSize}
                  onPageSizeChange={handleItcPageSizeChange}
                  onPrev={() => setItcPage((p) => Math.max(1, p - 1))}
                  onNext={() =>
                    setItcPage((p) =>
                      Math.min(itcPageData.total_pages, p + 1)
                    )
                  }
                />
                )}
              </>
            )}
              </>
            )}
          </div>
        )}

        {/* Risk */}
        {resultsTab === "risk" &&
          summary &&
          summary.wrongful_risk_count === 0 &&
          summary.missed_itc_count > 0 && (
          <div className={sectionContainerClass}>
            <div className="flex gap-3">
              <Shield className="mt-0.5 h-5 w-5 shrink-0 text-[#DC2626]" />
              <p className="text-[13px] text-gray-600">
                No compliance risk detected for this period.
              </p>
            </div>
          </div>
        )}

        {resultsTab === "risk" && summary && summary.wrongful_risk_count > 0 && (
          <div className={sectionContainerClass}>
            <SectionHeader
              title="ITC at Risk — Not in GSTR-2B"
              dotColor="#DC2626"
              badges={[
                {
                  label: "ITC AT RISK — NOT IN GSTR-2B",
                  amount: summary.wrongful_risk_total_amount,
                  variant: "risk",
                },
                {
                  label: "PURCHASE VALUE AT RISK",
                  amount: summary.wrongful_risk_purchase_total_amount ?? 0,
                  variant: "neutral",
                  sublabel: "Total invoice exposure",
                },
              ]}
              actions={
                <button
                  type="button"
                  disabled={riskCsvDownloading}
                  className={csvDownloadBtnClass}
                  onClick={() => void downloadRiskCsv()}
                >
                  {riskCsvDownloading ? (
                    <Loader2 className="h-4 w-4 shrink-0 animate-spin text-gray-400" />
                  ) : null}
                  Download CSV
                </button>
              }
            />

            <div className="mb-6">
              <h3 className="mb-4 text-base font-semibold text-gray-900">
                Top Suppliers by ITC at Risk — Not in GSTR-2B
              </h3>
              {((riskGroupBySupplier
                ? riskAllRowsLoading && !riskAllRows
                : riskLoading && !riskPageData)) && (
                <div className="animate-pulse space-y-2 py-2">
                  <div className="h-8 rounded bg-gray-100" />
                  <div className="h-8 rounded bg-gray-100/90" />
                  <div className="h-8 rounded bg-gray-100/80" />
                </div>
              )}
              {!(riskGroupBySupplier
                ? riskAllRowsLoading && !riskAllRows
                : riskLoading && !riskPageData) &&
                topSuppliersByRisk.length === 0 && (
                  <p className="text-sm text-gray-500">
                    No supplier risk data available.
                  </p>
                )}
              {!(riskGroupBySupplier
                ? riskAllRowsLoading && !riskAllRows
                : riskLoading && !riskPageData) &&
                topSuppliersByRisk.length > 0 && (
                  <>
                    <div className={tableWrapClass}>
                      <table className={topSuppliersTableClass}>
                        <thead className={tableHeadClass}>
                          <tr>
                            <th className={topSuppliersThGstin}>Supplier GSTIN</th>
                            <th className={topSuppliersThTradeName}>Trade Name</th>
                            <th className={topSuppliersThInvoiceCount}>
                              Invoice Count
                            </th>
                            <th className={topSuppliersThTotal}>
                              ITC at Risk — Not in GSTR-2B
                            </th>
                            <th className={topSuppliersThImpact}>Impact</th>
                          </tr>
                        </thead>
                        <tbody>
                          {topSuppliersByRisk.map((s) => (
                            <tr key={s.gstin} className={tableRowClass}>
                              <td className={topSuppliersTdGstin}>
                                <GstinCell gstin={s.gstin} />
                              </td>
                              <td className={topSuppliersTdTradeName}>
                                <HoverTextCell
                                  text={s.tradeName}
                                  displayClassName="text-[13px] font-medium text-gray-800"
                                />
                              </td>
                              <td className={topSuppliersTdInvoiceCount}>
                                {s.count.toLocaleString("en-IN")}
                              </td>
                              <td className={topSuppliersTdTotal}>
                                <AmountDisplay amount={s.total} />
                              </td>
                              <td className={topSuppliersTdImpact}>
                                <ImpactBadge level={s.impact} />
                              </td>
                            </tr>
                          ))}
                        </tbody>
                      </table>
                    </div>
                    <div className="mt-3 text-right">
                      <Link
                        href={`/reconcile/runs/${runId}/vendors`}
                        className="text-[13px] font-medium text-[var(--ink)] hover:underline"
                      >
                        View full vendor intelligence →
                      </Link>
                    </div>
                  </>
                )}
            </div>

            <div className={`${filterToolbarClass}`}>
              <div className={`${filterRowClass}`}>
                <input
                  type="text"
                  className={filterGstinInputClass}
                  placeholder="Filter by GSTIN..."
                  value={riskFilters.supplier_gstin}
                  onChange={(e) =>
                    setRiskFilters((f) => ({
                      ...f,
                      supplier_gstin: e.target.value,
                    }))
                  }
                />
              </div>
              <div className={`${filterRowClass}`}>
                <input
                  type="text"
                  inputMode="decimal"
                  className={filterAmountInputClass}
                  placeholder="₹ Min"
                  value={riskFilters.amount_min}
                  onChange={(e) =>
                    setRiskFilters((f) => ({ ...f, amount_min: e.target.value }))
                  }
                />
                <input
                  type="text"
                  inputMode="decimal"
                  className={filterAmountInputClass}
                  placeholder="₹ Max"
                  value={riskFilters.amount_max}
                  onChange={(e) =>
                    setRiskFilters((f) => ({ ...f, amount_max: e.target.value }))
                  }
                />
                <select
                  className={filterDropdownClass}
                  value={riskFilters.risk_level}
                  onChange={(e) =>
                    setRiskFilters((f) => ({
                      ...f,
                      risk_level: e.target.value,
                    }))
                  }
                >
                  <option value="">All</option>
                  <option value="high">High</option>
                  <option value="medium">Medium</option>
                  <option value="low">Low</option>
                </select>
                <select
                  className={filterSortDropdownClass}
                  aria-label="Sort by"
                  value={riskSort}
                  onChange={(e) =>
                    setRiskSort(e.target.value as ReconcileSortValue)
                  }
                >
                  {RECONCILE_SORT_OPTIONS_BASE.map((opt) => (
                    <option key={opt.value} value={opt.value}>
                      {opt.label}
                    </option>
                  ))}
                </select>
                <button
                  type="button"
                  className={`${filterToggleClass} ${
                    riskGroupBySupplier
                      ? filterToggleActiveClass
                      : filterToggleIdleClass
                  }`}
                  onClick={() => {
                    setRiskGroupBySupplier((on) => {
                      if (on) setRiskExpandedSupplier(null);
                      return !on;
                    });
                  }}
                >
                  Group by Supplier
                </button>
                {(hasActiveRiskFilters(riskFilters) || !!docTypeFilterRisk) && (
                  <button
                    type="button"
                    className="h-9 text-[13px] font-medium text-[var(--ink)] hover:underline"
                    onClick={() => {
                      setDocTypeFilterRisk("");
                      setRiskFilters({
                        amount_min: "",
                        amount_max: "",
                        supplier_gstin: "",
                        risk_level: "",
                      });
                    }}
                  >
                    Clear filters
                  </button>
                )}
              </div>
            </div>

            {riskGroupBySupplier ? (
              <>
                {(riskAllRowsError || (riskError && !riskAllRows)) && (
                  <SectionError
                    message={sectionLoadError("Failed to load.")}
                    onRetry={() => void mutateRiskAllRows()}
                  />
                )}
                {!riskAllRowsError && (
                  <SupplierGroupView<ReconcileRow>
                    groups={riskSupplierGroups}
                    expandedGstin={riskExpandedSupplier}
                    onToggleExpand={(gstin) =>
                      setRiskExpandedSupplier((prev) =>
                        prev === gstin ? null : gstin
                      )
                    }
                    amountLabel="ITC at Risk — Not in GSTR-2B"
                    grandTotal={summary.wrongful_risk_total_amount}
                    loading={riskAllRowsLoading && !riskAllRows}
                    onGenerateFollowup={(invoices) =>
                      openFollowupLetter(invoices)
                    }
                    followupDisabled={isRunFinalized || !authToken}
                    renderInvoices={(invoices) => (
                      <div className={decisionTableWrapClass}>
                        <table className={decisionTableClass}>
                          <thead className={tableHeadClass}>
                            <tr>
                              <th className={decisionTh("invoice")}>Invoice#</th>
                              <th className={decisionTh("date")}>Date</th>
                              <th className={decisionTh("amount", "right")}>
                                ITC at Risk — Not in GSTR-2B
                              </th>
                              <th className={decisionTh("impact")}>Impact</th>
                              <th className={decisionTh("what")}>WHAT</th>
                              <th className={decisionTh("status")}>Status</th>
                              <th className={decisionTh("notice", "right")}>
                                Follow-up
                              </th>
                            </tr>
                          </thead>
                          <tbody>
                            {invoices.map((row) => (
                              <tr key={row.id} className={tableRowClass}>
                                <td className={decisionTd("invoice")}>
                                  <HoverTextCell
                                    text={row.invoice_number}
                                    displayClassName="text-[13px] font-medium text-gray-800"
                                  />
                                </td>
                                <td
                                  className={`${decisionTd("date")} text-[13px] text-gray-500`}
                                >
                                  {formatDate(row.invoice_date)}
                                </td>
                                <td className={decisionTd("amount")}>
                                  <AmountDisplay amount={row.amount} />
                                </td>
                                <td className={decisionTd("impact")}>
                                  <ImpactBadge
                                    level={getImpactLevel(
                                      row.amount,
                                      summary.wrongful_risk_total_amount
                                    )}
                                  />
                                </td>
                                <td className={decisionTd("what")}>
                                  <HoverTextCell
                                    text={row.decision_what}
                                    displayClassName="text-[13px] text-gray-600"
                                  />
                                </td>
                                <td className={decisionTd("status")}>
                                  <DecisionStatusPill
                                    status={effectiveStatus(row)}
                                  />
                                </td>
                                <td
                                  className={decisionTd("notice", {
                                    align: "right",
                                  })}
                                >
                                  <button
                                    type="button"
                                    disabled={isRunFinalized || !authToken}
                                    className="max-w-full rounded-lg border border-[#E5E7EB] bg-white px-2 py-1.5 text-[10px] font-medium leading-tight text-[var(--ink)] hover:bg-[#F5F5F6] disabled:cursor-not-allowed disabled:opacity-50"
                                    onClick={() => openFollowupLetter([row])}
                                  >
                                    Generate follow-up letter
                                  </button>
                                </td>
                              </tr>
                            ))}
                          </tbody>
                        </table>
                      </div>
                    )}
                  />
                )}
              </>
            ) : (
              <>
            {riskError && (
              <SectionError
                message={sectionLoadError("Failed to load.")}
                onRetry={() => void mutateRisk()}
              />
            )}
            {riskLoading && !riskPageData && !riskError && (
              <div className={decisionTableWrapClass}>
                <table className={decisionTableClass}>
                  <DecisionTableColGroup includeNotice />
                  <thead className={tableHeadClass}>
                    <tr>
                      {Array.from({ length: 12 }).map((_, i) => (
                        <th key={i} className="px-2 py-2">
                          <div className="h-4 w-14 max-w-full animate-pulse rounded bg-gray-200" />
                        </th>
                      ))}
                    </tr>
                  </thead>
                  <tbody>
                    {Array.from({ length: 8 }).map((_, r) => (
                      <tr key={r} className="border-b border-gray-100">
                        {Array.from({ length: 12 }).map((_, c) => (
                          <td key={c} className="px-2 py-2">
                            <div
                              className={`h-4 max-w-full animate-pulse rounded bg-gray-200 ${
                                c === 0
                                  ? "w-4"
                                  : c === 5
                                    ? "ml-auto w-20"
                                    : "w-24"
                              }`}
                            />
                          </td>
                        ))}
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
            {riskPageData && !riskError && (
              <>
                {followupSelectionHint && (
                  <p className="mb-3 text-[13px] text-amber-800">{followupSelectionHint}</p>
                )}
                {selectedIds.risk.size > 0 && (
                  <div className="mb-3 flex flex-wrap items-center gap-3 rounded-xl border border-[#F0F0F0] bg-[#FAFAFA] px-4 py-2.5 text-[13px]">
                    <span className="text-gray-600">{selectedIds.risk.size} selected</span>
                    <button
                      type="button"
                      disabled={
                        isRunFinalized ||
                        !authToken ||
                        riskRowsSelectedOnPage.length === 0 ||
                        riskSelectionGstinCount !== 1
                      }
                      title={
                        riskSelectionGstinCount !== 1
                          ? "Select invoices from one supplier only"
                          : undefined
                      }
                      className="rounded-full bg-[#F5F5F6] px-3 py-1.5 text-[13px] font-medium text-[var(--ink)] hover:bg-gray-200/70 disabled:cursor-not-allowed disabled:opacity-50"
                      onClick={() => tryOpenBulkFollowup()}
                    >
                      Generate follow-up letter
                    </button>
                    <button
                      type="button"
                      disabled={isRunFinalized}
                      className="rounded-lg border border-[#E5E7EB] bg-white px-3 py-1.5 text-[13px] font-medium text-gray-700 hover:bg-gray-50 disabled:cursor-not-allowed disabled:opacity-50"
                      onClick={() => {
                        const snap = new Set(selectedIds.risk);
                        void runBulkDecision("risk", Array.from(snap), "acted", snap);
                      }}
                    >
                      Mark as Acted
                    </button>
                    <button
                      type="button"
                      disabled={isRunFinalized}
                      className="rounded-lg border border-[#E5E7EB] bg-white px-3 py-1.5 text-[13px] font-medium text-gray-700 hover:bg-gray-50 disabled:cursor-not-allowed disabled:opacity-50"
                      onClick={() => {
                        const snap = new Set(selectedIds.risk);
                        void runBulkDecision("risk", Array.from(snap), "ignored", snap);
                      }}
                    >
                      Mark as Ignored
                    </button>
                    <button
                      type="button"
                      className="text-[13px] font-medium text-[var(--ink)] hover:underline"
                      onClick={() =>
                        setSelectedIds((p) => ({ ...p, risk: new Set() }))
                      }
                    >
                      Clear
                    </button>
                  </div>
                )}
                {riskPageData.data.length === 0 ? (
                  <EmptyTableState
                    title="No ITC at Risk — Not in GSTR-2B rows for this filter"
                    description="Adjust amount, GSTIN, or risk level filters to see compliance risk invoices."
                  />
                ) : (
                <DecisionInvoiceList
                  selectAll={
                    <>
                      <input
                        ref={riskHeaderRef}
                        type="checkbox"
                        disabled={isRunFinalized}
                        checked={
                          riskRows.length > 0 &&
                          riskRows.every((r) => selectedIds.risk.has(r.id))
                        }
                        onChange={(e) => {
                          const on = e.target.checked;
                          setSelectedIds((prev) => {
                            const next = {
                              ...prev,
                              risk: new Set(prev.risk),
                            };
                            if (on) riskRows.forEach((r) => next.risk.add(r.id));
                            else riskRows.forEach((r) => next.risk.delete(r.id));
                            return next;
                          });
                        }}
                        className="rounded border-gray-300"
                      />
                      <span className="text-[13px] font-medium text-gray-600">
                        Select all on this page
                      </span>
                    </>
                  }
                >
                  {riskRows.filter((r) => checkDocType(r, docTypeFilterRisk)).map((row, i) => (
                    <DecisionInvoiceCard
                      key={row.id}
                      index={(riskPage - 1) * riskPageData.limit + i + 1}
                      gstin={row.supplier_gstin}
                      invoiceNumber={row.invoice_number}
                      invoiceDate={formatDate(row.invoice_date)}
                      amount={row.amount}
                      amountCaption="ITC at Risk — Not in GSTR-2B"
                      selected={selectedIds.risk.has(row.id)}
                      checkboxDisabled={isRunFinalized}
                      onSelectChange={(checked) => {
                        setSelectedIds((prev) => {
                          const next = { ...prev, risk: new Set(prev.risk) };
                          if (checked) next.risk.add(row.id);
                          else next.risk.delete(row.id);
                          return next;
                        });
                      }}
                      impact={
                        <ImpactBadge level={getImpactLevel(row.amount, riskMax)} />
                      }
                      status={
                        <div className="flex flex-wrap items-center gap-2">
                          <DecisionStatusPill status={effectiveStatus(row)} />
                          {effectiveStatus(row) === "pending" ? (
                            <span className="text-[11px] font-medium text-gray-500">
                              {row.discrepancy_note || "Review required"}
                            </span>
                          ) : null}
                        </div>
                      }
                      meta={
                        <div className="flex flex-wrap items-center gap-1.5">
                          {row.match_confidence != null ? (
                            <MatchConfidenceBadge
                              score={row.match_confidence}
                              onClick={(e) => toggleRationale(e, row.id)}
                            />
                          ) : null}
                          {(row.compared_fields?.length ?? 0) > 0 ? (
                            <WhyRationaleButton
                              expanded={rationaleExpandedId === row.id}
                              onToggle={(e) => toggleRationale(e, row.id)}
                            />
                          ) : null}
                        </div>
                      }
                      trailing={
                        <button
                          type="button"
                          disabled={isRunFinalized || !authToken}
                          className="rounded-full bg-[var(--ink)] px-3.5 py-2 text-[12px] font-semibold text-white transition-opacity hover:opacity-90 disabled:cursor-not-allowed disabled:opacity-50"
                          onClick={() => openFollowupLetter([row])}
                        >
                          Generate follow-up letter
                        </button>
                      }
                      what={row.decision_what}
                      why={row.decision_why}
                      next={row.decision_next}
                      expandedContent={
                        rationaleExpandedId === row.id ? (
                          <ComparedFieldsPanel row={row} />
                        ) : null
                      }
                    />
                  ))}
                </DecisionInvoiceList>
                )}
                {riskPageData.data.length > 0 && (
                <ReconcilePaginationFooter
                  page={riskPageData.page}
                  totalPages={riskPageData.total_pages}
                  total={riskPageData.total}
                  limit={riskPageData.limit}
                  pageSizeOptions={RECONCILE_TABLE_PAGE_SIZE_OPTIONS}
                  pageSize={riskPageSize}
                  onPageSizeChange={handleRiskPageSizeChange}
                  onPrev={() => setRiskPage((p) => Math.max(1, p - 1))}
                  onNext={() =>
                    setRiskPage((p) =>
                      Math.min(riskPageData.total_pages, p + 1)
                    )
                  }
                />
                )}
              </>
            )}
              </>
            )}
          </div>
        )}

        {summary &&
          resultsTab === "matched" &&
          typeof summary.late_match_count === "number" &&
          summary.late_match_count > 0 && (
            <div className={sectionContainerClass}>
              <p className="mb-4 text-lg font-semibold text-gray-900">
                {summary.late_match_count.toLocaleString("en-IN")} invoices
                matched from previous periods
              </p>
              {lateMatchesLoading && (
                <div className="animate-pulse space-y-2 py-2">
                  <div className="h-6 rounded bg-[#F0F0F0]" />
                  <div className="h-6 rounded bg-[#F0F0F0]" />
                  <div className="h-6 rounded bg-[#F0F0F0]" />
                </div>
              )}
              {!lateMatchesLoading &&
                (lateMatchesError || !(lateMatchesData?.data?.length ?? 0)) && (
                  <p className="text-sm text-gray-600">
                    No late match data available.
                  </p>
                )}
              {!lateMatchesLoading &&
                (lateMatchesData?.data?.length ?? 0) > 0 && (
                  <div className={decisionTableWrapClass}>
                    <table className={decisionTableClass}>
                      <thead className={tableHeadClass}>
                        <tr>
                          <th className={`${tableHeadCellClass} w-[22%]`}>Supplier</th>
                          <th className={`${tableHeadCellClass} w-[18%]`}>Invoice#</th>
                          <th className={`${tableHeadCellClass} w-[22%]`}>Original Period</th>
                          <th className={`${tableHeadCellClass} w-[22%]`}>GSTR-2B Period</th>
                          <th className={`${tableHeadCellClass} w-[16%] text-right`}>
                            Months Late
                          </th>
                        </tr>
                      </thead>
                      <tbody>
                        {(lateMatchesData?.data ?? []).map((row, idx) => (
                          <tr
                            key={`${row.supplier_gstin}-${row.invoice_number}-${idx}`}
                            className={tableRowClass}
                          >
                            <td className={`${tableCellClass} max-w-0 overflow-visible font-mono text-[13px] text-gray-500`}>
                              <GstinCell gstin={row.supplier_gstin} />
                            </td>
                            <td className={`${tableCellClass} max-w-0 overflow-visible`}>
                              <HoverTextCell
                                text={row.invoice_number}
                                displayClassName="text-[13px] font-medium text-gray-800"
                              />
                            </td>
                            <td className={`${tableCellClass} text-[13px] text-gray-500`}>
                              {row.original_period || "—"}
                            </td>
                            <td className={`${tableCellClass} text-[13px] text-gray-500`}>
                              {row.gstr2b_period || "—"}
                            </td>
                            <td className={`${tableCellClass} text-right text-[13px] font-semibold tabular-nums text-gray-900`}>
                              {row.months_late}
                            </td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                )}
            </div>
          )}

        {/* Matched */}
        {resultsTab === "matched" && (
        <div className="p-0">
          <div className="flex flex-wrap items-center gap-2.5 border-b border-[#F1F5F9] bg-[#FAFAFA] px-6 py-3">
            <input
              type="search"
              className={`w-64 ${filterInputClass}`}
              placeholder="Search supplier GSTIN or invoice number…"
              value={matchedSearch}
              onChange={(e) => setMatchedSearch(e.target.value)}
            />
            <select
              className={filterDropdownClass}
              value={docTypeFilterMatched}
              onChange={(e) => setDocTypeFilterMatched(e.target.value)}
            >
              <option value="">All types</option>
              <option value="Invoice">Invoice</option>
              <option value="Credit Note">Credit Note</option>
              <option value="Debit Note">Debit Note</option>
            </select>
            <select
              className={filterDropdownClass}
              value={matchedFilters.match_level}
              onChange={(e) =>
                setMatchedFilters((f) => ({
                  ...f,
                  match_level: e.target.value,
                }))
              }
            >
              <option value="">All levels</option>
              <option value="EXACT">EXACT</option>
              <option value="FUZZY">FUZZY</option>
              <option value="MANUAL">MANUAL</option>
            </select>
            <select
              className={filterDropdownClass}
              value={matchedFilters.ims_status}
              onChange={(e) =>
                setMatchedFilters((f) => ({
                  ...f,
                  ims_status: e.target.value,
                }))
              }
            >
              <option value="">All IMS</option>
              <option value="accepted">Accepted</option>
              <option value="rejected">Rejected</option>
              <option value="pending">Pending</option>
              <option value="no_action_taken">No action</option>
            </select>
            <select
              className={filterSortDropdownClass}
              aria-label="Sort by"
              value={matchedSort}
              onChange={(e) =>
                setMatchedSort(e.target.value as ReconcileSortValue)
              }
            >
              {RECONCILE_SORT_OPTIONS_WITH_CONFIDENCE.map((opt) => (
                <option key={opt.value} value={opt.value}>
                  {opt.label}
                </option>
              ))}
            </select>
            {(hasActiveMatchedFilters(debouncedMatchedSearch, matchedFilters) || !!docTypeFilterMatched) && (
              <button
                type="button"
                className="h-8 text-[12px] font-medium text-[#2563EB] hover:underline"
                onClick={() => {
                  setMatchedSearch("");
                  setDebouncedMatchedSearch("");
                  setDocTypeFilterMatched("");
                  setMatchedFilters({
                    match_level: "",
                    has_notes: false,
                    section_17_5: false,
                    amount_min: "",
                    amount_max: "",
                    ims_status: "",
                  });
                  setMatchedPage(1);
                }}
              >
                Clear filters
              </button>
            )}
            
            {summary && (
              <div className="ml-auto flex items-center gap-2">
                <div className="flex items-center gap-1.5 rounded-full border border-[#E2E8F0] bg-white px-2.5 py-1 text-[11px] font-medium text-[#475569]">
                  <span className="h-1.5 w-1.5 rounded-full bg-[#16A34A]" aria-hidden />
                  {(summary?.clean_matched_count ?? summary?.matched_count ?? 0).toLocaleString("en-IN")} Matched
                </div>
                <div className="flex items-center gap-1.5 rounded-full border border-[#E2E8F0] bg-white px-2.5 py-1 text-[11px] font-medium text-[#475569]">
                  <span className="h-1.5 w-1.5 rounded-full bg-[#D97706]" aria-hidden />
                  {((summary?.clean_matched_count ?? summary?.matched_count ?? 0) - (summary?.exact_match_count ?? 0)).toLocaleString("en-IN")} Non-exact
                </div>
              </div>
            )}
          </div>

          {matchedError && (
            <SectionError
              message={sectionLoadError("Failed to load.")}
              onRetry={() => void mutateMatched()}
            />
          )}
          {matchedLoading && !matchedData && !matchedError && (
            <div className="animate-pulse space-y-2 p-4">
              <div className="h-8 rounded bg-gray-100" />
              <div className="h-8 rounded bg-gray-100/80" />
            </div>
          )}
          {matchedData &&
            !matchedError &&
            matchedData.data.length === 0 && (
              <EmptyTableState
                title="No clean matches for this filter"
                description="Try adjusting the search or filters to see matched records."
                action={
                  <button
                    type="button"
                    className="rounded-lg border border-[#E8E8EC] bg-white px-3.5 py-2 text-[13px] font-medium text-gray-700 hover:bg-gray-50"
                    onClick={() => {
                      setMatchedSearch("");
                      setDebouncedMatchedSearch("");
                      setDocTypeFilterMatched("");
                      setMatchedFilters({
                        match_level: "",
                        has_notes: false,
                        section_17_5: false,
                        amount_min: "",
                        amount_max: "",
                        ims_status: "",
                      });
                      setMatchedPage(1);
                    }}
                  >
                    Clear filters
                  </button>
                }
              />
            )}
          {matchedData && !matchedError && matchedData.data.length > 0 && (
            <>
              <div className={tableWrapClass}>
                <table className={matchedTableClass}>
                  <thead className={tableHeadClass}>
                    <tr>
                      <th className={matchedThGstin}>Supplier GSTIN</th>
                      <th className={matchedThInvoice}>Invoice #</th>
                      <th className={matchedThDate}>Date</th>
                      <th className={matchedThAmount}>Amount</th>
                      <th className={matchedThMatchLevel}>Match</th>
                      <th className={matchedThConfidence}>Confidence</th>
                      <th className={matchedThIms}>IMS</th>
                      <th className={matchedThDiscrepancy}>Discrepancy</th>
                      <th className={matchedThNotes}>Notes</th>
                    </tr>
                  </thead>
                  <tbody>
                    {matchedData.data.filter(r => checkDocType(r, docTypeFilterMatched)).map((row) => {
                      let taxDiff = formatTaxDifferenceDisplay(
                        row.tax_difference_paise,
                        row.discrepancy_note
                      );

                      if (taxDiff.display === "₹0.00" && row.discrepancy_reason) {
                        const reasonDisplay = row.discrepancy_reason.replace(/_/g, " ");
                        const titleCased = reasonDisplay === reasonDisplay.toUpperCase()
                          ? reasonDisplay.charAt(0).toUpperCase() + reasonDisplay.slice(1).toLowerCase()
                          : reasonDisplay;
                        taxDiff = { display: titleCased, tooltip: row.discrepancy_reason };
                      }

                      return (
                      <Fragment key={row.id}>
                      <tr
                        className={`group cursor-pointer ${tableRowClass}`}
                        onClick={() => {
                          setActiveRecord(row);
                          setDrawerDecisionError(null);
                          setNotePostError(null);
                        }}
                      >
                        <td className={matchedTdGstin}>
                          <GstinCell gstin={row.supplier_gstin} />
                        </td>
                        <td className={matchedTdInvoice}>
                          <HoverTextCell
                            text={row.invoice_number}
                            displayClassName="text-[12px] font-medium text-[#2563EB] hover:underline"
                          />
                        </td>
                        <td className={matchedTdDate}>
                          {formatDate(row.invoice_date)}
                        </td>
                        <td className={matchedTdAmount}>
                          <AmountDisplay amount={row.amount} />
                        </td>
                        <td className={matchedTdMatchLevel}>
                          <div className="flex flex-wrap items-center gap-1.5">
                            <MatchLevelBadge level={row.match_level} />
                            {row.auto_approved ? (
                              <span
                                className="inline-flex items-center whitespace-nowrap rounded bg-emerald-50 px-1.5 py-0.5 text-[10px] font-semibold text-emerald-700 ring-1 ring-inset ring-emerald-600/20"
                                title="Promoted from Review Required by confidence threshold"
                              >
                                Auto
                              </span>
                            ) : null}
                            <ItcIneligibleBadge
                              itcAvailable={row.itc_available}
                              itcReason={row.itc_reason}
                            />
                          </div>
                        </td>
                        <td className={matchedTdConfidence}>
                          <div className="flex items-center gap-1.5">
                            <div className="h-1 w-8 overflow-hidden rounded-full bg-[#F1F5F9] shrink-0">
                              <div
                                className="h-full rounded-full transition-all"
                                style={{
                                  width: `${Math.round(Math.min(100, Math.max(0, row.confidence_score)))}%`,
                                  backgroundColor: row.match_level === "MANUAL" ? "#2563EB" : "#16A34A",
                                }}
                              />
                            </div>
                            <span className="text-[11px] text-[#64748B]">
                              {Math.round(
                                Math.min(100, Math.max(0, row.confidence_score))
                              )}
                              %
                            </span>
                            {(row.compared_fields?.length ?? 0) > 0 && (
                              <WhyRationaleButton
                                expanded={rationaleExpandedId === row.id}
                                onToggle={(e) => toggleRationale(e, row.id)}
                              />
                            )}
                          </div>
                        </td>
                        <td className={matchedTdIms}>
                          <ImsStatusBadge status={row.ims_status} />
                        </td>
                        <td className={matchedTdDiscrepancy}>
                          <span className={taxDiff.display === "₹0.00" || taxDiff.display === "₹0" ? "text-xs text-[#94A3B8]" : "text-xs font-semibold text-[#DC2626]"}>
                            {taxDiff.display}
                          </span>
                        </td>
                        <td className={matchedTdNotes}>
                          {row.notes_count > 0 ? (
                            <span className="inline-flex rounded bg-[#F1F5F9] px-1.5 py-0.5 text-[10px] font-medium text-[#64748B]">
                              {row.notes_count}
                            </span>
                          ) : (
                            <span className="text-xs text-[#CBD5E1]">—</span>
                          )}
                        </td>
                      </tr>
                      {rationaleExpandedId === row.id && (
                        <ComparedFieldsAccordionRow row={row} colSpan={9} />
                      )}
                      </Fragment>
                    );
                    })}
                  </tbody>
                </table>
              </div>
              <ReconcilePaginationFooter
                page={matchedData.page}
                totalPages={matchedData.total_pages}
                total={matchedData.total}
                limit={matchedData.limit}
                pageSizeOptions={RECONCILE_TABLE_PAGE_SIZE_OPTIONS}
                pageSize={matchedPageSize}
                onPageSizeChange={handleMatchedPageSizeChange}
                onPrev={() => setMatchedPage((p) => Math.max(1, p - 1))}
                onNext={() =>
                  setMatchedPage((p) =>
                    Math.min(matchedData.total_pages, p + 1)
                  )
                }
              />
            </>
          )}
        </div>
        )}

        {resultsTab === "gstr3b" && authToken && (
          <Gstr3bSummaryView
            runId={runId}
            authToken={authToken}
            variant="embedded"
          />
        )}

        {resultsTab === "followup" && authToken && (
          <SupplierFollowupAuditLogPanel runId={runId} authToken={authToken} />
        )}

        {resultsTab === "einvoice" && (
          <EInvoiceCheckPanel
            runId={runId}
            clientGstinId={summary?.client_gstin_id ?? summary?.client_gstin ?? undefined}
            period={summary?.period ?? undefined}
            authToken={authToken ?? undefined}
          />
        )}

        {/* Duplicate Entries */}
        {resultsTab === "duplicate_entry" && (
          <div className={sectionContainerClass}>
            <h2 className="mb-1 text-[15px] font-semibold tracking-tight text-gray-900">
              Duplicate Entries{" "}
              {summary != null && (
                <span className="font-normal text-gray-500">
                  ({(summary.duplicate_entry_count ?? 0).toLocaleString("en-IN")})
                </span>
              )}
            </h2>
            <p className="mb-5 text-[12px] leading-relaxed text-gray-500">
              Extra purchase-register bookings of an invoice that already matched
              GSTR-2B. These are data-entry duplicates in your books — not missing
              from GSTR-2B, and not included in ITC at Risk — Not in GSTR-2B.
            </p>
            {(summary?.duplicate_entry_count ?? 0) > 0 && (
              <div className={`${filterToolbarClass}`}>
                <div className={filterRowClass}>
                  <select
                    className={filterSortDropdownClass}
                    aria-label="Sort by"
                    value={duplicateEntrySort}
                    onChange={(e) =>
                      setDuplicateEntrySort(e.target.value as ReconcileSortValue)
                    }
                  >
                    {RECONCILE_SORT_OPTIONS_BASE.map((opt) => (
                      <option key={opt.value} value={opt.value}>
                        {opt.label}
                      </option>
                    ))}
                  </select>
                </div>
              </div>
            )}
            {(summary?.duplicate_entry_count ?? 0) <= 0 ? (
              <p className="text-sm text-gray-500">No duplicate entries in this run.</p>
            ) : duplicateEntryLoading ? (
              <p className="text-sm text-gray-500">Loading…</p>
            ) : duplicateEntryError ? (
              <p className="text-sm text-red-600">
                Failed to load duplicate entries
                {typeof (duplicateEntryError as { detail?: unknown }).detail ===
                "string"
                  ? `: ${(duplicateEntryError as { detail: string }).detail}`
                  : "."}
              </p>
            ) : (
              <div className="overflow-x-auto rounded-lg border border-[#E8E8EC]">
                <table className="min-w-full text-left text-[13px]">
                  <thead className="bg-[#FAFAFB] text-[11px] uppercase tracking-wide text-gray-500">
                    <tr>
                      <th className="px-3 py-2 font-medium">Supplier GSTIN</th>
                      <th className="px-3 py-2 font-medium">Invoice</th>
                      <th className="px-3 py-2 font-medium">Date</th>
                      <th className="px-3 py-2 font-medium text-right">Tax (₹)</th>
                      <th className="px-3 py-2 font-medium">Canonical PR</th>
                      <th className="px-3 py-2 font-medium">Action</th>
                    </tr>
                  </thead>
                  <tbody>
                    {sortedDuplicateEntries.map((row) => (
                      <tr key={row.id} className="border-t border-[#EFEFF2]">
                        <td className="px-3 py-2 font-mono text-[12px]">
                          {row.supplier_gstin || "—"}
                        </td>
                        <td className="px-3 py-2">{row.invoice_number || "—"}</td>
                        <td className="px-3 py-2">{row.invoice_date || "—"}</td>
                        <td className="px-3 py-2 text-right">
                          {row.amount != null
                            ? (Math.abs(row.amount) / 100).toLocaleString("en-IN", {
                                minimumFractionDigits: 2,
                                maximumFractionDigits: 2,
                              })
                            : "—"}
                        </td>
                        <td className="px-3 py-2 font-mono text-[11px] text-gray-600">
                          {row.matched_pr_id || "—"}
                        </td>
                        <td className="px-3 py-2 text-gray-600">
                          {row.decision_next || "Remove or mark the extra booking."}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </div>
        )}

        {/* Notes — Not Matched (credit/debit notes quarantined from invoice matching) */}
        {resultsTab === "unmatched_notes" && (
          <div className={sectionContainerClass}>
            <h2 className="mb-1 text-[15px] font-semibold tracking-tight text-gray-900">
              Notes — Not Auto-Matched{" "}
              {summary != null && (
                <span className="font-normal text-gray-500">
                  ({(summary.unmatched_notes_count ?? 0).toLocaleString("en-IN")})
                </span>
              )}
            </h2>
            <p className="mb-5 text-[12px] leading-relaxed text-gray-500">
              Credit and debit notes from the purchase register were quarantined
              before matching and are{" "}
              <span className="font-medium text-gray-700">
                not automatically reconciled
              </span>
              . They are kept out of Matched, Review Required, and ITC at Risk —
              Not in GSTR-2B. Full matching against GSTR-2B note[] is not
              implemented yet — review these manually.
            </p>
            {(summary?.unmatched_notes_count ?? 0) <= 0 ? (
              <p className="text-sm text-gray-500">
                No credit/debit note rows in this run.
              </p>
            ) : unmatchedNotesLoading ? (
              <p className="text-sm text-gray-500">Loading…</p>
            ) : unmatchedNotesError ? (
              <p className="text-sm text-red-600">
                Failed to load notes
                {typeof (unmatchedNotesError as { detail?: unknown }).detail ===
                "string"
                  ? `: ${(unmatchedNotesError as { detail: string }).detail}`
                  : "."}
              </p>
            ) : (
              <div className="overflow-x-auto rounded-lg border border-[#E8E8EC]">
                <table className="min-w-full text-left text-[13px]">
                  <thead className="bg-[#FAFAFB] text-[11px] uppercase tracking-wide text-gray-500">
                    <tr>
                      <th className="px-3 py-2 font-medium">Type</th>
                      <th className="px-3 py-2 font-medium">Supplier GSTIN</th>
                      <th className="px-3 py-2 font-medium">Note No</th>
                      <th className="px-3 py-2 font-medium">Date</th>
                      <th className="px-3 py-2 font-medium text-right">
                        Amount (₹)
                      </th>
                      <th className="px-3 py-2 font-medium">Note</th>
                    </tr>
                  </thead>
                  <tbody>
                    {(unmatchedNotesData?.invoices ?? []).map((row) => (
                      <tr key={row.id} className="border-t border-[#EFEFF2]">
                        <td className="px-3 py-2 text-gray-700">
                          {row.match_status === "CREDIT_NOTE"
                            ? "Credit Note"
                            : row.match_status === "DEBIT_NOTE"
                              ? "Debit Note"
                              : row.match_status || "Note"}
                        </td>
                        <td className="px-3 py-2 font-mono text-[12px]">
                          {row.supplier_gstin || "—"}
                        </td>
                        <td className="px-3 py-2">{row.invoice_number || "—"}</td>
                        <td className="px-3 py-2">{row.invoice_date || "—"}</td>
                        <td className="px-3 py-2 text-right">
                          {row.amount != null
                            ? (row.amount / 100).toLocaleString("en-IN", {
                                minimumFractionDigits: 2,
                                maximumFractionDigits: 2,
                              })
                            : "—"}
                        </td>
                        <td className="px-3 py-2 text-gray-600">
                          {row.decision_why ||
                            "CDN↔GSTR-2B note matching not implemented yet."}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </div>
        )}

        {/* Review Required */}
        {resultsTab === "review_required" && (
        <div className={sectionContainerClass}>
          <h2 className="mb-1 text-base sm:text-lg font-bold tracking-tight text-gray-900">
            {tResults("reviewRequired")}{" "}
            {summary != null && (
              <span className="font-normal text-gray-500">
                ({(summary.review_required_count ?? 0).toLocaleString("en-IN")})
              </span>
            )}
          </h2>
          <p className="mb-3.5 text-xs sm:text-[13px] leading-relaxed text-gray-500">
            These records were matched but have discrepancies or low confidence that need manual verification before finalizing.
          </p>

          <div className="mb-5 flex flex-col gap-2.5 rounded-xl border border-[#EFEFF2] bg-[#FAFAFA] px-4 py-3.5 sm:flex-row sm:items-center sm:justify-between">
            <div className="min-w-0">
              <p className="text-xs sm:text-[13px] font-semibold text-[var(--ink)]">
                {tResults("autoApproveThreshold")}
              </p>
              <p className="mt-0.5 text-xs leading-relaxed text-gray-500">
                {tResults("autoApproveDesc")}{" "}
                <Link
                  href="/settings/reconciliation"
                  className="font-medium text-gray-700 underline underline-offset-2 hover:text-[var(--ink)]"
                >
                  {tResults("fullSettings")}
                </Link>
              </p>
            </div>
            <div className="flex shrink-0 items-center gap-2">
              <input
                type="range"
                min={0}
                max={100}
                disabled={!canEditAutoApproveThreshold || autoApproveSaving}
                value={autoApproveThreshold}
                onChange={(e) =>
                  setAutoApproveThreshold(Number(e.target.value))
                }
                className="h-1.5 w-28 accent-[var(--ink)]"
                aria-label="Auto-approve confidence threshold"
              />
              <input
                type="number"
                min={0}
                max={100}
                disabled={!canEditAutoApproveThreshold || autoApproveSaving}
                value={autoApproveThreshold}
                onChange={(e) =>
                  setAutoApproveThreshold(
                    Number.isFinite(Number(e.target.value))
                      ? Number(e.target.value)
                      : DEFAULT_AUTO_APPROVE_THRESHOLD
                  )
                }
                className="h-8 w-14 rounded-lg border border-[#E5E5EA] bg-white px-2 text-center text-xs font-semibold tabular-nums text-[var(--ink)] disabled:opacity-50"
                aria-label="Auto-approve threshold percent"
              />
              <span className="text-xs text-gray-500 font-medium">%</span>
              <button
                type="button"
                disabled={!canEditAutoApproveThreshold || autoApproveSaving}
                onClick={() => void saveAutoApproveThreshold()}
                className="inline-flex h-8 items-center rounded-full bg-[var(--ink)] px-3.5 text-xs font-semibold text-white transition-opacity hover:opacity-90 disabled:cursor-not-allowed disabled:opacity-50"
              >
                {autoApproveSaving ? (
                  <Loader2 className="h-3.5 w-3.5 animate-spin" />
                ) : (
                  tResults("saveThreshold")
                )}
              </button>
            </div>
          </div>

          <div className={filterToolbarClass}>
            <input
              type="search"
              className={`w-full ${filterInputClass}`}
              placeholder={tResults("searchPlaceholder")}
              value={reviewRequiredSearch}
              onChange={(e) => setReviewRequiredSearch(e.target.value)}
            />
            <div className={filterRowClass}>
              <select
                className={filterDropdownClass}
                value={docTypeFilterReviewRequired}
                onChange={(e) => setDocTypeFilterReviewRequired(e.target.value)}
              >
                <option value="">{tResults("allTypes")}</option>
                <option value="Invoice">{tResults("typeInvoice")}</option>
                <option value="Credit Note">{tResults("typeCreditNote")}</option>
                <option value="Debit Note">{tResults("typeDebitNote")}</option>
              </select>
              <select
                className={filterDropdownClass}
                value={reviewRequiredFilters.match_level}
                onChange={(e) =>
                  setReviewRequiredFilters((f) => ({
                    ...f,
                    match_level: e.target.value,
                  }))
                }
              >
                <option value="">{tResults("allLevels")}</option>
                <option value="EXACT">EXACT</option>
                <option value="FUZZY">FUZZY</option>
                <option value="MANUAL">MANUAL</option>
              </select>
              <input
                className={filterAmountInputClass}
                placeholder="₹ Min"
                value={reviewRequiredFilters.amount_min}
                onChange={(e) =>
                  setReviewRequiredFilters((f) => ({
                    ...f,
                    amount_min: e.target.value,
                  }))
                }
              />
              <input
                className={filterAmountInputClass}
                placeholder="₹ Max"
                value={reviewRequiredFilters.amount_max}
                onBlur={() => setReviewRequiredPage(1)}
                onChange={(e) =>
                  setReviewRequiredFilters((f) => ({
                    ...f,
                    amount_max: e.target.value,
                  }))
                }
              />
              <select
                className={filterSortDropdownClass}
                aria-label="Sort by"
                value={reviewRequiredSort}
                onChange={(e) =>
                  setReviewRequiredSort(e.target.value as ReconcileSortValue)
                }
              >
                {RECONCILE_SORT_OPTIONS_WITH_CONFIDENCE.map((opt) => (
                  <option key={opt.value} value={opt.value}>
                    {opt.label}
                  </option>
                ))}
              </select>
              <button
                type="button"
                className={`${filterToggleClass} ${
                  reviewRequiredFilters.has_notes
                    ? filterToggleActiveClass
                    : filterToggleIdleClass
                }`}
                onClick={() =>
                  setReviewRequiredFilters((f) => ({
                    ...f,
                    has_notes: !f.has_notes,
                  }))
                }
              >
                Has Notes
              </button>
              <button
                type="button"
                className={`${filterToggleClass} ${
                  reviewRequiredFilters.section_17_5
                    ? "border-gray-800 bg-gray-900/[0.04] text-gray-800"
                    : filterToggleIdleClass
                }`}
                onClick={() =>
                  setReviewRequiredFilters((f) => ({
                    ...f,
                    section_17_5: !f.section_17_5,
                  }))
                }
              >
                Section 17(5)
              </button>
              {(!!debouncedReviewRequiredSearch.trim() ||
                !!reviewRequiredFilters.match_level ||
                reviewRequiredFilters.has_notes ||
                reviewRequiredFilters.section_17_5 ||
                !!reviewRequiredFilters.amount_min.trim() ||
                !!reviewRequiredFilters.amount_max.trim() ||
                !!docTypeFilterReviewRequired) && (
                <button
                  type="button"
                  className="h-9 text-[13px] font-medium text-[var(--ink)] hover:underline"
                  onClick={() => {
                    setReviewRequiredSearch("");
                    setDebouncedReviewRequiredSearch("");
                    setDocTypeFilterReviewRequired("");
                    setReviewRequiredFilters({
                      match_level: "",
                      has_notes: false,
                      section_17_5: false,
                      amount_min: "",
                      amount_max: "",
                      ims_status: "",
                    });
                    setReviewRequiredPage(1);
                  }}
                >
                  Clear all filters
                </button>
              )}
            </div>
          </div>

          {reviewRequiredError && (
            <SectionError
              message={sectionLoadError("Failed to load.")}
              onRetry={() => void mutateReviewRequired()}
            />
          )}
          {reviewRequiredLoading && !reviewRequiredData && !reviewRequiredError && (
            <div className="animate-pulse space-y-2 py-4">
              <div className="h-8 rounded bg-gray-100" />
              <div className="h-8 rounded bg-gray-100/80" />
            </div>
          )}
          {reviewRequiredData &&
            !reviewRequiredError &&
            reviewRequiredData.data.length === 0 && (
              <EmptyTableState
                title="No records requiring review"
                description="Try adjusting the search or filters to find discrepancies that need verification."
                action={
                  <button
                    type="button"
                    className="rounded-lg border border-[#E8E8EC] bg-white px-3.5 py-2 text-[13px] font-medium text-gray-700 hover:bg-gray-50"
                    onClick={() => {
                      setReviewRequiredSearch("");
                      setDebouncedReviewRequiredSearch("");
                      setDocTypeFilterReviewRequired("");
                      setReviewRequiredFilters({
                        match_level: "",
                        has_notes: false,
                        section_17_5: false,
                        amount_min: "",
                        amount_max: "",
                        ims_status: "",
                      });
                      setReviewRequiredPage(1);
                    }}
                  >
                    Clear filters
                  </button>
                }
              />
            )}
          {reviewRequiredData && !reviewRequiredError && reviewRequiredData.data.length > 0 && (
            <>
              <DecisionInvoiceList>
                {(() => {
                  const validRows = reviewRequiredData.data
                    .filter((r) => checkDocType(r, docTypeFilterReviewRequired))
                    .filter(
                      (r) =>
                        r.supplier_gstin ||
                        r.invoice_number ||
                        (r.amount && r.amount > 0)
                    );
                  return validRows.map((row, i) => {
                    let taxDiff = formatTaxDifferenceDisplay(
                      row.tax_difference_paise,
                      row.discrepancy_note
                    );

                    if (taxDiff.display === "₹0.00" && row.discrepancy_reason) {
                      const localizedReason = localizeDiscrepancyReason(row.discrepancy_reason, locale);
                      taxDiff = { display: localizedReason, tooltip: row.discrepancy_reason };
                    }

                    return (
                      <DecisionInvoiceCard
                        key={row.id}
                        index={
                          (reviewRequiredData.page - 1) * reviewRequiredData.limit +
                          i +
                          1
                        }
                        gstin={row.supplier_gstin}
                        invoiceNumber={row.invoice_number}
                        invoiceDate={formatDate(row.invoice_date)}
                        amount={row.amount}
                        onOpen={() => {
                          setActiveRecord(row);
                          setDrawerDecisionError(null);
                          setNotePostError(null);
                        }}
                        status={
                          <div className="flex flex-wrap items-center gap-2">
                            <MatchLevelBadge level={row.match_level} />
                            <span className="rounded-full bg-[#F5F5F6] px-2.5 py-0.5 text-[11px] font-semibold text-gray-600">
                              {tResults("percentConfidence", {
                                score: Math.round(
                                  Math.min(100, Math.max(0, row.confidence_score))
                                ),
                              })}
                            </span>
                            {row.auto_approved ? (
                              <span className="inline-flex items-center whitespace-nowrap rounded-full bg-emerald-50 px-1.5 py-0.5 text-[10px] font-semibold text-emerald-700 ring-1 ring-inset ring-emerald-600/20">
                                {tResults("autoApproved")}
                              </span>
                            ) : null}
                            {row.notes_count > 0 ? (
                              <span className="inline-flex rounded-full bg-amber-50 px-2 py-0.5 text-[11px] font-medium text-amber-700">
                                {tResults("notesCount", { count: row.notes_count })}
                              </span>
                            ) : null}
                          </div>
                        }
                        meta={
                          <div className="flex flex-wrap items-center gap-1.5">
                            <span
                              className="rounded-full bg-white px-2.5 py-0.5 text-[11px] font-medium text-gray-600 ring-1 ring-[#E8E8EC]"
                              title={taxDiff.tooltip ?? undefined}
                            >
                              {taxDiff.display}
                            </span>
                            {(row.compared_fields?.length ?? 0) > 0 ? (
                              <WhyRationaleButton
                                expanded={rationaleExpandedId === row.id}
                                onToggle={(e) => toggleRationale(e, row.id)}
                              />
                            ) : null}
                            {row.match_confidence != null ? (
                              <MatchConfidenceBadge
                                score={row.match_confidence}
                                onClick={(e) => toggleRationale(e, row.id)}
                              />
                            ) : null}
                          </div>
                        }
                        what={row.decision_what}
                        why={row.decision_why}
                        next={row.decision_next}
                        expandedContent={
                          rationaleExpandedId === row.id ? (
                            <ComparedFieldsPanel row={row} />
                          ) : null
                        }
                      />
                    );
                  });
                })()}
              </DecisionInvoiceList>
              <ReconcilePaginationFooter
                page={reviewRequiredData.page}
                totalPages={reviewRequiredData.total_pages}
                total={reviewRequiredData.total}
                limit={reviewRequiredData.limit}
                pageSizeOptions={RECONCILE_TABLE_PAGE_SIZE_OPTIONS}
                pageSize={reviewRequiredPageSize}
                onPageSizeChange={handleReviewRequiredPageSizeChange}
                onPrev={() => setReviewRequiredPage((p) => Math.max(1, p - 1))}
                onNext={() =>
                  setReviewRequiredPage((p) =>
                    Math.min(reviewRequiredData.total_pages, p + 1)
                  )
                }
              />
            </>
          )}
        </div>
        )}

        {/* IMS Actions — CA confirm before GSTN writeback */}
        {resultsTab === "ims" && (
        <>
        {authToken ? (
          <ImsActionPanel
            runId={runId}
            authToken={authToken}
          />
        ) : (
          <div className={sectionContainerClass}>
            <p className="text-sm text-gray-500">
              Sign in to load IMS recommendations for this run.
            </p>
          </div>
        )}
        </>
        )}

        {/* Rule 37 */}
        {resultsTab === "rule37" && (
        <>
        {authToken ? (
          <AuditObservationsPanel
            runId={runId}
            authToken={authToken}
            refreshKey={rule37SummaryRefreshKey}
          />
        ) : null}
        <div className={sectionContainerClass}>
          <button
            type="button"
            className="flex w-full items-center justify-between gap-3 text-left transition-all duration-150"
            onClick={() => setRule37Open((o) => !o)}
          >
            <span className="flex min-w-0 flex-1 flex-wrap items-center gap-2">
              <span
                className="h-2 w-2 shrink-0 rounded-full bg-[#D97706]"
                aria-hidden
              />
              <span className="text-lg font-semibold text-gray-900">
                ITC at Risk — Rule 37 (Unpaid 180+ Days)
              </span>
              {rule37Data != null && (
                <span className="rounded-full bg-gray-100 px-2 py-0.5 text-[11px] font-medium text-gray-500">
                  {rule37Data.total}
                </span>
              )}
              {rule37Data != null &&
              rule37Data.data.length === rule37Data.total &&
              unresolvedRule37Count === 0 &&
              rule37Data.total > 0 ? (
                <span className="rounded-full bg-green-50 px-2 py-0.5 text-[11px] font-medium text-green-600">
                  all acted
                </span>
              ) : null}
            </span>
            <span
              className="flex shrink-0 items-center gap-3"
              onClick={(e) => e.stopPropagation()}
              onKeyDown={(e) => e.stopPropagation()}
              role="presentation"
            >
              {rule37TotalAmount != null && (
                <SectionAmountBadge
                  label="CONFIRMED ITC AT RISK — RULE 37"
                  amount={rule37TotalAmount}
                  variant="rule37"
                  sublabel={rule37HeaderSublabel}
                />
              )}
              <ChevronDown
                className={`h-5 w-5 shrink-0 text-gray-400 transition-transform duration-150 ${
                  rule37Open ? "rotate-180" : ""
                }`}
              />
            </span>
          </button>
          {rule37Open && (
            <div className="mt-5 border-t border-[#F0F0F0] pt-5">
              {authToken && (
                <Rule37SummarySection
                  runId={runId}
                  authToken={authToken}
                  refreshKey={rule37SummaryRefreshKey}
                />
              )}
              {rule37Error && (
                <SectionError
                  message={sectionLoadError("Failed to load.")}
                  onRetry={() => void mutateRule37()}
                />
              )}
              {rule37Loading && !rule37Data && !rule37Error && (
                <p className="animate-pulse text-sm text-gray-400">Loading…</p>
              )}
              {rule37Data && !rule37Error && rule37Data.total === 0 && (
                <p className="text-sm text-gray-500">
                  {formatRule37EmptyStateMessage(rule37SummaryData?.summary)}
                </p>
              )}
              {rule37Data &&
                !rule37Error &&
                rule37Data.data.map((row) => {
                  const u = row.rule37_urgency ?? "MEDIUM";
                  const actionStatus =
                    localRule37ActionStatus.get(row.id) ??
                    row.rule37_action_status ??
                    null;
                  const acted =
                    actionStatus === "resolved" ||
                    actionStatus === "acknowledged" ||
                    actionStatus === "rejected";
                  const isPendingReview = actionStatus === "pending_review";
                  const meta = row.rule37_review_metadata;

                  return (
                    <div
                      key={row.id}
                      className={`mb-3 rounded-2xl border border-l-4 p-5 ${
                        isPendingReview
                          ? "border-amber-200 border-l-amber-500 bg-amber-50/20"
                          : `border-[#F0F0F0] bg-white ${rule37BorderClass(u, acted)}`
                      }`}
                    >
                      <div className="flex flex-wrap items-start justify-between gap-3">
                        <div className="flex flex-wrap items-center gap-x-4 gap-y-1 text-[13px]">
                          <GstinCell
                            gstin={row.supplier_gstin}
                            className="font-mono text-[12px] text-gray-400"
                          />
                          <span className="font-medium text-gray-800">
                            {row.invoice_number}
                          </span>
                          <span className="text-gray-400">
                            {formatDate(row.invoice_date)}
                          </span>
                          <AmountDisplay amount={row.amount} />
                        </div>
                        {isPendingReview ? (
                          <span className="inline-flex items-center gap-1 rounded-full bg-amber-100 px-2.5 py-0.5 text-xs font-semibold text-amber-800">
                            ⚠️ Pending Tally Review
                          </span>
                        ) : actionStatus === "rejected" ? (
                          <span className="inline-flex items-center rounded-full bg-gray-100 px-2.5 py-0.5 text-xs font-medium text-gray-500">
                            Match Rejected ✗
                          </span>
                        ) : !acted ? (
                          <Rule37SeverityLabel urgency={u} />
                        ) : null}
                      </div>

                      {isPendingReview && (
                        <div className="mt-3 rounded-xl border border-amber-200 bg-amber-50/80 p-3.5 text-xs text-amber-900">
                          <p className="font-semibold text-amber-950">
                            ⚠️ Tally Payment Match — Manual Confirmation Required
                          </p>
                          <div className="mt-2 grid grid-cols-1 gap-x-4 gap-y-1.5 sm:grid-cols-2">
                            <div>
                              <span className="text-amber-700">Tally Ledger Party:</span>{" "}
                              <strong className="font-medium text-amber-950">
                                {meta?.party || "—"}
                              </strong>
                            </div>
                            <div>
                              <span className="text-amber-700">PR Supplier Name:</span>{" "}
                              <strong className="font-medium text-amber-950">
                                {meta?.supplier_name || "—"}
                              </strong>
                            </div>
                            <div>
                              <span className="text-amber-700">Party Name Confidence:</span>{" "}
                              <strong className="font-medium text-amber-950">
                                {meta?.party_sim != null
                                  ? `${Math.round(meta.party_sim * 100)}%`
                                  : "0%"}
                              </strong>{" "}
                              <span className="text-amber-600">
                                (Auto-settle gate:{" "}
                                {Math.round((meta?.party_gate_min || 0.82) * 100)}%)
                              </span>
                            </div>
                            <div>
                              <span className="text-amber-700">Bill Ref Match Score:</span>{" "}
                              <strong className="font-medium text-amber-950">
                                {meta?.bill_ref_score != null
                                  ? `${Math.round(meta.bill_ref_score * 100)}%`
                                  : "—"}
                              </strong>
                            </div>
                            {meta?.amount_paid != null && (
                              <div>
                                <span className="text-amber-700">Payment Amount:</span>{" "}
                                <strong className="font-medium text-amber-950">
                                  ₹{Number(meta.amount_paid).toLocaleString("en-IN")}
                                </strong>
                              </div>
                            )}
                          </div>
                        </div>
                      )}

                      <p className="mt-3 text-[13px] font-medium text-gray-700">
                        {row.decision_what ?? "—"}
                      </p>
                      <p className="mt-1 text-[13px] text-gray-400">
                        {row.decision_why ?? "—"}
                      </p>
                      <p className="mt-2 text-[13px] font-medium text-[var(--ink)]">
                        {row.decision_next ?? "—"}
                      </p>
                      <DecisionDiagnosticsBlock row={row} />
                      <div className="mt-4 flex flex-wrap justify-end gap-2">
                        {isPendingReview ? (
                          <>
                            <button
                              type="button"
                              disabled={rule37UpdatingIds.has(row.id)}
                              className="rounded-lg bg-amber-600 px-4 py-2 text-[13px] font-medium text-white shadow-sm transition-all duration-150 hover:bg-amber-700 disabled:cursor-not-allowed disabled:opacity-50"
                              onClick={() => {
                                const actionId = row.rule37_action_id;
                                setRule37UpdatingIds((prev) => new Set(prev).add(row.id));
                                const promise = actionId
                                  ? tallyBridgeApi.resolveReview(authToken!, actionId, { status: "resolved" })
                                  : apiFetch(`/api/tally-sync/review/${encodeURIComponent(row.id)}/resolve`, {
                                      method: "POST",
                                      token: authToken!,
                                      body: JSON.stringify({ status: "resolved" }),
                                    });
                                promise
                                  .then(() => {
                                    setLocalRule37ActionStatus((prev) => {
                                      const next = new Map(prev);
                                      next.set(row.id, "resolved");
                                      return next;
                                    });
                                    addToast("Match approved & settled", "success");
                                    setRule37SummaryRefreshKey((k) => k + 1);
                                    void mutateRule37();
                                  })
                                  .catch((err) => {
                                    addToast(err.message || "Failed to resolve review", "error");
                                  })
                                  .finally(() => {
                                    setRule37UpdatingIds((prev) => {
                                      const next = new Set(prev);
                                      next.delete(row.id);
                                      return next;
                                    });
                                  });
                              }}
                            >
                              Approve & Settle
                            </button>
                            <button
                              type="button"
                              disabled={rule37UpdatingIds.has(row.id)}
                              className="rounded-lg border border-amber-300 bg-white px-4 py-2 text-[13px] font-medium text-gray-700 transition-all duration-150 hover:bg-gray-50 disabled:cursor-not-allowed disabled:opacity-50"
                              onClick={() => {
                                const actionId = row.rule37_action_id;
                                setRule37UpdatingIds((prev) => new Set(prev).add(row.id));
                                const promise = actionId
                                  ? tallyBridgeApi.resolveReview(authToken!, actionId, { status: "rejected" })
                                  : apiFetch(`/api/tally-sync/review/${encodeURIComponent(row.id)}/resolve`, {
                                      method: "POST",
                                      token: authToken!,
                                      body: JSON.stringify({ status: "rejected" }),
                                    });
                                promise
                                  .then(() => {
                                    setLocalRule37ActionStatus((prev) => {
                                      const next = new Map(prev);
                                      next.set(row.id, "rejected");
                                      return next;
                                    });
                                    addToast("Match rejected", "success");
                                    setRule37SummaryRefreshKey((k) => k + 1);
                                    void mutateRule37();
                                  })
                                  .catch((err) => {
                                    addToast(err.message || "Failed to resolve review", "error");
                                  })
                                  .finally(() => {
                                    setRule37UpdatingIds((prev) => {
                                      const next = new Set(prev);
                                      next.delete(row.id);
                                      return next;
                                    });
                                  });
                              }}
                            >
                              Reject Match
                            </button>
                          </>
                        ) : actionStatus === "resolved" ? (
                          <span className="inline-flex items-center rounded-lg bg-gray-100 px-4 py-2 text-[13px] text-gray-400">
                            Marked as Settled ✓
                            {row.rule37_payment_coverage === "partial" ? (
                              <span className="ml-1 text-amber-600">
                                (Partial)
                              </span>
                            ) : null}
                          </span>
                        ) : actionStatus === "acknowledged" ? (
                          <span className="inline-flex items-center rounded-lg bg-gray-100 px-4 py-2 text-[13px] text-gray-400">
                            ITC Reversal Noted ✓
                          </span>
                        ) : actionStatus === "rejected" ? (
                          <span className="inline-flex items-center rounded-lg bg-gray-100 px-4 py-2 text-[13px] text-gray-400">
                            Match Rejected ✗
                          </span>
                        ) : (
                          <>
                            <button
                              type="button"
                              disabled={rule37UpdatingIds.has(row.id)}
                              className="rounded-lg border border-[#E5E7EB] bg-white px-4 py-2 text-[13px] font-medium text-gray-700 transition-all duration-150 hover:bg-gray-50 disabled:cursor-not-allowed disabled:opacity-50"
                              onClick={() =>
                                setRule37MarkPaidTarget({
                                  id: row.id,
                                  invoice_number: row.invoice_number,
                                  supplier_gstin: row.supplier_gstin,
                                  invoice_amount:
                                    row.invoice_amount ?? row.amount,
                                })
                              }
                            >
                              Mark as Settled
                            </button>
                            <button
                              type="button"
                              disabled={rule37UpdatingIds.has(row.id)}
                              className="rounded-lg border border-[#FEE2E2] bg-white px-4 py-2 text-[13px] font-medium text-red-600 transition-all duration-150 hover:bg-red-50 disabled:cursor-not-allowed disabled:opacity-50"
                              onClick={() => void actOnRule37(row.id, "acknowledged")}
                            >
                              Reverse ITC
                            </button>
                          </>
                        )}
                      </div>
                    </div>
                  );
                })}
              <Rule37MarkPaidModal
                open={rule37MarkPaidTarget != null}
                row={rule37MarkPaidTarget}
                saving={
                  rule37MarkPaidTarget != null &&
                  rule37UpdatingIds.has(rule37MarkPaidTarget.id)
                }
                onClose={() => {
                  if (
                    rule37MarkPaidTarget &&
                    rule37UpdatingIds.has(rule37MarkPaidTarget.id)
                  ) {
                    return;
                  }
                  setRule37MarkPaidTarget(null);
                }}
                onSubmit={(payment) => {
                  if (!rule37MarkPaidTarget) return;
                  void actOnRule37(
                    rule37MarkPaidTarget.id,
                    "resolved",
                    payment
                  );
                }}
              />
              {rule37Data && !rule37Error && (
                  <ReconcilePaginationFooter
                    page={rule37Data.page}
                    totalPages={rule37Data.total_pages}
                    total={rule37Data.total}
                    limit={rule37Data.limit}
                    pageSizeOptions={RECONCILE_TABLE_PAGE_SIZE_OPTIONS}
                    pageSize={rule37PageSize}
                    onPageSizeChange={handleRule37PageSizeChange}
                    onPrev={() => setRule37Page((p) => Math.max(1, p - 1))}
                    onNext={() =>
                      setRule37Page((p) =>
                        Math.min(rule37Data.total_pages, p + 1)
                      )
                    }
                  />
                )}
            </div>
          )}
        </div>
        </>
        )}

        {/* Section 17(5) */}
        {resultsTab === "section17" && (
        <>
        {authToken ? (
          <AuditObservationsPanel
            runId={runId}
            authToken={authToken}
            refreshKey={rule37SummaryRefreshKey}
            filterSourceRule="BLOCKED_ITC_17_5"
          />
        ) : null}
        <div className={sectionContainerClass}>
          <button
            type="button"
            className="flex w-full items-center justify-between gap-3 text-left transition-all duration-150"
            onClick={() => setSection17Open((o) => !o)}
          >
            <span className="flex min-w-0 flex-1 flex-wrap items-center gap-2">
              <span
                className="h-2 w-2 shrink-0 rounded-full bg-gray-500"
                aria-hidden
              />
              <span className="text-lg font-semibold text-gray-900">
                Section 17(5) — Blocked ITC Flags
              </span>
              {section17Data != null && (
                <span className="rounded-full bg-gray-100 px-2 py-0.5 text-[11px] font-medium text-gray-500">
                  {section17Data.total}
                </span>
              )}
            </span>
            <ChevronDown
              className={`h-5 w-5 shrink-0 text-gray-400 transition-transform duration-150 ${
                section17Open ? "rotate-180" : ""
              }`}
            />
          </button>
          {section17Open && (
            <div className="mt-5 border-t border-[#F0F0F0] pt-5">
              {section17Error && (
                <SectionError
                  message={sectionLoadError("Failed to load.")}
                  onRetry={() => void mutateSection17()}
                />
              )}
              {section17Loading && !section17Data && !section17Error && (
                <p className="animate-pulse text-sm text-gray-400">Loading…</p>
              )}
              {section17Data && !section17Error && section17Data.total === 0 && (
                <p className="text-sm text-gray-500">
                  No Section 17(5) blocked ITC flags found.
                </p>
              )}
              {section17Data &&
                !section17Error &&
                section17Data.data.map((row) => (
                  <div
                    key={row.id}
                    className="mb-3 rounded-2xl border border-[#F0F0F0] border-l-4 border-l-gray-400 bg-white p-5"
                  >
                    <div className="flex flex-wrap items-start justify-between gap-3">
                      <div className="flex flex-wrap items-center gap-x-4 gap-y-1 text-[13px]">
                        <GstinCell
                          gstin={row.supplier_gstin}
                          className="font-mono text-[12px] text-gray-400"
                        />
                        <span className="font-medium text-gray-800">
                          {row.invoice_number}
                        </span>
                        <span className="text-gray-400">
                          {formatDate(row.invoice_date)}
                        </span>
                        <AmountDisplay amount={row.amount} />
                      </div>
                      {row.section_17_5_category && (
                        <span className="rounded-full bg-gray-100 px-2 py-0.5 text-[11px] font-medium text-gray-500">
                          {row.section_17_5_category}
                        </span>
                      )}
                    </div>
                    {row.discrepancy_note && (
                      <p className="mt-2 text-[12px] text-gray-400">
                        HSN {row.discrepancy_note}
                      </p>
                    )}
                    <p className="mt-3 text-[13px] font-medium text-gray-700">
                      {row.decision_what ?? "—"}
                    </p>
                    <p className="mt-1 text-[13px] text-gray-400">
                      {row.decision_why ?? "—"}
                    </p>
                    <p className="mt-2 text-[13px] font-medium text-[var(--ink)]">
                      {row.decision_next ?? "—"}
                    </p>
                    <DecisionDiagnosticsBlock row={row} />
                  </div>
                ))}
              {section17Data && !section17Error && (
                  <ReconcilePaginationFooter
                    page={section17Data.page}
                    totalPages={section17Data.total_pages}
                    total={section17Data.total}
                    limit={section17Data.limit}
                    pageSizeOptions={RECONCILE_TABLE_PAGE_SIZE_OPTIONS}
                    pageSize={section17PageSize}
                    onPageSizeChange={handleSection17PageSizeChange}
                    onPrev={() => setSection17Page((p) => Math.max(1, p - 1))}
                    onNext={() =>
                      setSection17Page((p) =>
                        Math.min(section17Data.total_pages, p + 1)
                      )
                    }
                  />
                )}
            </div>
          )}
        </div>
        </>
        )}

        {/* RCM Reconciliation */}
        {resultsTab === "rcm" && (
        <>
        {authToken ? (
          <RcmReconciliationPanel
            runId={runId}
            authToken={authToken}
          />
        ) : (
          <div className={sectionContainerClass}>
            <p className="text-sm text-gray-500">
              Sign in to view RCM 3-Way Reconciliation.
            </p>
          </div>
        )}
        </>
        )}
        </div>
      </div>

      {/* Drawer */}
      {activeRecord && (
        <>
          <button
            type="button"
            aria-label="Close"
            className="fixed inset-0 z-40 bg-black/40"
            onClick={() => setActiveRecord(null)}
          />
          <aside className="fixed bottom-0 right-0 top-0 z-50 flex h-full w-full flex-col border-l border-[#F0F0F0] bg-white sm:w-[640px]">
            <div className="sticky top-0 z-10 flex shrink-0 items-start justify-between border-b border-gray-100 bg-white px-4 py-3">
              <div>
                <p className="font-mono text-xs text-gray-500">
                  {activeRecord.supplier_gstin}
                </p>
                <p className="font-semibold text-gray-900">
                  {activeRecord.invoice_number}
                  <span className="font-normal text-gray-400"> · </span>
                  {formatDate(activeRecord.invoice_date)}
                </p>
              </div>
              <button
                type="button"
                className="inline-flex min-h-[44px] min-w-[44px] items-center justify-center rounded p-1 text-gray-500 hover:bg-gray-100"
                onClick={() => setActiveRecord(null)}
              >
                <X className="h-5 w-5" />
              </button>
            </div>

            <div className="min-h-0 flex-1 space-y-4 overflow-y-auto p-4">
              <div className="grid grid-cols-2 gap-4">
                <div>
                  <p className="mb-2 text-xs font-semibold uppercase tracking-wide text-gray-400">
                    GSTR-2B Data
                  </p>
                </div>
                <div>
                  <p className="mb-2 text-xs font-semibold uppercase tracking-wide text-gray-400">
                    Purchase Register Data
                  </p>
                </div>
                {COMPARE_FIELDS.map(({ label, keys }) => {
                  const leftRaw = readDataField(activeRecord.gstr2b_data, keys);
                  const rightRaw = readDataField(
                    activeRecord.purchase_register_data,
                    keys
                  );
                  const left = formatCompareFieldDisplay(label, leftRaw);
                  const right = formatCompareFieldDisplay(label, rightRaw);
                  const mismatch =
                    !normCompare(leftRaw, rightRaw) &&
                    !(leftRaw === "—" && rightRaw === "—");
                  return (
                    <div key={label} className="contents">
                      <div className={mismatch ? "rounded-lg border border-[#F0F0F0] bg-[#FAFAFA] p-2" : ""}>
                        <p className="text-[11px] text-gray-400">{label}</p>
                        <p
                          className={`text-[13px] ${
                            mismatch
                              ? "font-medium text-[#D97706]"
                              : "text-gray-800"
                          }`}
                        >
                          {left}
                        </p>
                      </div>
                      <div className={mismatch ? "rounded-lg border border-[#F0F0F0] bg-[#FAFAFA] p-2" : ""}>
                        <p className="text-[11px] text-gray-400">{label}</p>
                        <p
                          className={`text-[13px] ${
                            mismatch
                              ? "font-medium text-[#D97706]"
                              : "text-gray-800"
                          }`}
                        >
                          {right}
                        </p>
                      </div>
                    </div>
                  );
                })}
              </div>

              <div className="rounded-2xl border border-[#F0F0F0] bg-white p-5">
                <p className="mb-4 text-[15px] font-semibold text-gray-900">
                  Decision
                </p>
                <p className="text-[11px] font-semibold uppercase tracking-wider text-gray-400">
                  WHAT IS WRONG
                </p>
                <p className="mb-3 text-[13px] font-medium text-gray-700">
                  {activeRecord.decision_what ?? "—"}
                </p>
                <p className="text-[11px] font-semibold uppercase tracking-wider text-gray-400">
                  WHY
                </p>
                <p className="mb-3 text-[13px] italic text-gray-400">
                  {activeRecord.decision_why ?? "—"}
                </p>
                <p className="text-[11px] font-semibold uppercase tracking-wider text-gray-400">
                  WHAT TO DO NEXT
                </p>
                <p className="mb-3 text-[13px] font-medium text-[var(--ink)]">
                  {activeRecord.decision_next ?? "—"}
                </p>
                <DecisionDiagnosticsBlock row={activeRecord} />
                <div className="mb-3 flex flex-wrap gap-2">
                  <DecisionStatusPill
                    status={effectiveStatus(activeRecord)}
                  />
                  {activeRecord.decision_type && (
                    <span className="inline-flex rounded-full bg-gray-200 px-2 py-0.5 text-xs text-gray-700">
                      {activeRecord.decision_type}
                    </span>
                  )}
                </div>
                <div className="flex flex-wrap gap-2">
                  <button
                    type="button"
                    disabled={isRunFinalized}
                    className="rounded-lg border border-[#E5E7EB] bg-white px-4 py-2 text-[13px] font-medium text-gray-700 hover:bg-gray-50 disabled:cursor-not-allowed disabled:opacity-50"
                    onClick={() =>
                      void runSingleDecision(activeRecord.id, "acted")
                    }
                  >
                    Mark as Acted
                  </button>
                  <button
                    type="button"
                    disabled={isRunFinalized}
                    className="rounded-lg border border-[#E5E7EB] bg-white px-4 py-2 text-[13px] font-medium text-gray-700 hover:bg-gray-50 disabled:cursor-not-allowed disabled:opacity-50"
                    onClick={() =>
                      void runSingleDecision(activeRecord.id, "ignored")
                    }
                  >
                    Mark as Ignored
                  </button>
                </div>
                {drawerDecisionError && (
                  <p className="mt-2 text-sm text-red-600">
                    {drawerDecisionError}
                  </p>
                )}
              </div>

              <div>
                <div className="mb-2 flex items-center gap-2">
                  <h3 className="font-semibold text-gray-900">Notes</h3>
                  <span className="rounded-full bg-gray-100 px-2 py-0.5 text-xs text-gray-600">
                    {drawerNotes.length}
                  </span>
                </div>
                {drawerNotesLoading && (
                  <div className="animate-pulse space-y-2 py-2">
                    <div className="h-12 rounded bg-gray-100" />
                    <div className="h-12 rounded bg-gray-100" />
                    <div className="h-12 rounded bg-gray-100" />
                  </div>
                )}
                {!drawerNotesLoading && (
                  <ul className="space-y-3">
                    {[...drawerNotes].reverse().map((n) => (
                      <li key={n.id} className="flex gap-3">
                        <div className="flex h-8 w-8 shrink-0 items-center justify-center rounded-full bg-gray-200 text-sm font-medium text-gray-600">
                          {(n.author_name || "?").charAt(0).toUpperCase()}
                        </div>
                        <div>
                          <div className="flex flex-wrap items-baseline gap-2">
                            <span className="text-sm font-medium text-gray-900">
                              {n.author_name}
                            </span>
                            <span className="text-xs text-gray-400">
                              {timeAgo(n.created_at)}
                            </span>
                          </div>
                          <p className="mt-1 text-sm text-gray-700">
                            {n.note_text}
                          </p>
                        </div>
                      </li>
                    ))}
                  </ul>
                )}
                <div className="mt-4">
                  <textarea
                    rows={3}
                    className="w-full rounded border border-gray-300 p-2 text-sm"
                    placeholder="Add a note..."
                    value={newNoteText}
                    onChange={(e) => setNewNoteText(e.target.value)}
                  />
                  <div className="mt-2 flex flex-col gap-2 sm:flex-row sm:justify-end">
                    {notePostError && (
                      <p className="mr-auto text-sm text-red-600">
                        {notePostError}
                      </p>
                    )}
                    <button
                      type="button"
                      disabled={notePosting || !newNoteText.trim()}
                      className="inline-flex min-h-[44px] w-full items-center justify-center gap-1 rounded bg-gray-900 px-3 py-1 text-sm text-white disabled:opacity-40 sm:w-auto"
                      onClick={() => void submitNote()}
                    >
                      {notePosting && (
                        <Loader2 className="h-4 w-4 animate-spin" />
                      )}
                      Add Note
                    </button>
                  </div>
                </div>
              </div>
            </div>
          </aside>
        </>
      )}

      {/* Sticky bottom bar */}
      <div className="fixed bottom-0 left-0 md:left-[216px] right-0 z-40 flex items-center justify-between border-t border-[#E2E8F0] bg-white px-6 py-3 shadow-md">
        <div className="flex items-center gap-6">
          <div className="flex items-center gap-1.5 text-xs font-medium text-[#475569]">
            <span className="font-bold text-[#16A34A]">✓</span> {tResults("matchedReviewed")}
          </div>
          <div className="flex items-center gap-1.5 text-xs font-medium text-[#475569]">
            {(summary?.review_required_count ?? 0) > 0 ? (
              <>
                <span className="font-bold text-[#D97706]">○</span> {tResults("reviewRequiredPending", { count: summary?.review_required_count ?? 0 })}
              </>
            ) : (
              <>
                <span className="font-bold text-[#16A34A]">✓</span> {tResults("reviewRequiredReviewed")}
              </>
            )}
          </div>
          <div className="flex items-center gap-1.5 text-xs font-medium text-[#475569]">
            {(summary?.missed_itc_count ?? 0) > 0 ? (
              <>
                <span className="font-bold text-[#D97706]">○</span> {tResults("missedItcPending", { count: summary?.missed_itc_count ?? 0 })}
              </>
            ) : (
              <>
                <span className="font-bold text-[#16A34A]">✓</span> {tResults("missedItcReviewed")}
              </>
            )}
          </div>
        </div>
        <div className="flex items-center gap-3">
          <div className="text-xs text-[#94A3B8]">
            {isRunFinalized
              ? tResults("finalizedBy", { name: summary?.finalized_by_name || "Admin" })
              : summary?.user_role === "staff"
                ? tResults("onlyAdminCanLock")
                : tResults("completeAllReviews")}
          </div>
          {!isRunFinalized ? (
            <button
              type="button"
              disabled={summary?.user_role !== "admin"}
              className="rounded-[6px] bg-[#0F172A] px-4 py-2 text-xs sm:text-[13px] font-bold text-white transition-colors hover:bg-[#1E293B] disabled:cursor-not-allowed disabled:opacity-40"
              onClick={() => setFinalizeModalOpen(true)}
            >
              {tResults("lockRun")}
            </button>
          ) : (
            <span className="rounded-[6px] bg-emerald-100 px-3.5 py-1.5 text-xs font-bold text-emerald-800">
              {tResults("locked")}
            </span>
          )}
        </div>
      </div>

      {followupLetterRows && summary && authToken && (
        <SupplierFollowupLetterModal
          open
          onClose={() => setFollowupLetterRows(null)}
          runId={runId}
          taxPeriod={summary.period}
          clientName={summary.client_name}
          clientGstin={summary.client_gstin ?? ""}
          rows={followupLetterRows}
          token={authToken}
        />
      )}

      {deleteModalOpen && canDeleteRun && (
        <div
          className="fixed inset-0 z-50 flex items-center justify-center bg-black/50"
          role="presentation"
          onClick={(e) => {
            if (e.target === e.currentTarget) closeDeleteModal();
          }}
        >
          <div
            className="relative mx-4 w-full max-w-lg rounded-2xl border border-[#F0F0F0] bg-white p-6"
            role="dialog"
            aria-labelledby="delete-run-title"
          >
            <div className="pr-8">
              <h2
                id="delete-run-title"
                className="text-lg font-semibold text-gray-900"
              >
                Delete reconciliation run
              </h2>
              <p className="mt-2 text-sm text-gray-600">
                Delete this reconciliation run? This will permanently delete all
                matched records, mismatches, and uploaded files. This cannot be
                undone.
              </p>
            </div>
            <button
              type="button"
              disabled={deleting}
              className="absolute right-4 top-4 inline-flex min-h-[44px] min-w-[44px] items-center justify-center rounded text-gray-500 hover:bg-gray-100 disabled:cursor-not-allowed disabled:opacity-50"
              aria-label="Close"
              onClick={closeDeleteModal}
            >
              <X className="h-5 w-5" />
            </button>
            {deleteError && (
              <p className="mt-4 text-sm text-red-600" role="alert">
                {deleteError}
              </p>
            )}
            <div className="mt-6 flex flex-col-reverse gap-2 sm:flex-row sm:justify-end">
              <button
                type="button"
                disabled={deleting}
                className="inline-flex min-h-[44px] items-center justify-center rounded-full border border-gray-300 px-4 py-2 text-sm font-medium text-gray-700 hover:bg-gray-50 disabled:cursor-not-allowed disabled:opacity-50"
                onClick={closeDeleteModal}
              >
                Cancel
              </button>
              <button
                type="button"
                disabled={deleting}
                className="inline-flex min-h-[44px] items-center justify-center gap-2 rounded-full bg-red-600 px-4 py-2 text-sm font-medium text-white hover:bg-red-700 disabled:cursor-not-allowed disabled:opacity-50"
                onClick={() => void submitDeleteRun()}
              >
                {deleting && (
                  <Loader2 className="h-4 w-4 shrink-0 animate-spin" />
                )}
                {deleting ? "Deleting..." : "Delete permanently"}
              </button>
            </div>
          </div>
        </div>
      )}

      {finalizeModalOpen && (
        <div
          className="fixed inset-0 z-50 flex items-center justify-center bg-black/50"
          role="presentation"
          onClick={(e) => {
            if (e.target === e.currentTarget) closeFinalizeModal();
          }}
        >
          <div className="relative mx-4 max-h-[90vh] w-full max-w-lg overflow-y-auto rounded-2xl border border-[#F0F0F0] bg-white p-6">
            <div className="pr-8">
              <h2 className="text-lg font-semibold text-gray-900">
                Finalize Reconciliation
              </h2>
              <p className="mt-1 text-sm text-gray-500">
                Check all items to confirm. This action is permanent and cannot be
                undone.
              </p>
            </div>
            <button
              type="button"
              disabled={finalizing}
              className="absolute right-4 top-4 inline-flex min-h-[44px] min-w-[44px] items-center justify-center rounded text-gray-500 hover:bg-gray-100 disabled:cursor-not-allowed disabled:opacity-50"
              aria-label="Close"
              onClick={closeFinalizeModal}
            >
              <X className="h-5 w-5" />
            </button>

            <div className="mt-4 space-y-3">
              {FINALIZE_CHECKLIST_ROWS.map(({ key, label }) => {
                const checked = checklist[key];
                return (
                  <button
                    key={key}
                    type="button"
                    disabled={finalizing}
                    onClick={() =>
                      setChecklist((c) => ({ ...c, [key]: !c[key] }))
                    }
                    className="flex w-full cursor-pointer items-start gap-3 rounded text-left disabled:cursor-not-allowed disabled:opacity-60"
                  >
                    <span
                      className={`mt-0.5 flex h-5 w-5 shrink-0 items-center justify-center rounded-full border-2 ${
                        checked
                          ? "border-[var(--ink)] bg-[var(--ink)] text-white"
                          : "border-gray-300 bg-white"
                      }`}
                      aria-hidden
                    >
                      {checked ? (
                        <Check className="h-3 w-3 stroke-[3]" />
                      ) : null}
                    </span>
                    <span
                      className={`text-sm ${
                        checked
                          ? "text-gray-400 line-through"
                          : "text-gray-700"
                      }`}
                    >
                      {label}
                    </span>
                  </button>
                );
              })}
            </div>

            {(() => {
              const n = Object.values(checklist).filter(Boolean).length;
              return (
                <div className="mt-4">
                  <p className="text-sm text-gray-500">
                    {n} of 5 items confirmed
                  </p>
                  <div className="mt-1 h-1.5 w-full rounded-full bg-[#F0F0F0]">
                    <div
                      className="h-1.5 rounded-full bg-[var(--ink)] transition-all duration-150"
                      style={{ width: `${(n / 5) * 100}%` }}
                    />
                  </div>
                </div>
              );
            })()}

            <div className="mt-6 flex flex-wrap items-center justify-between gap-3">
              <button
                type="button"
                disabled={finalizing}
                className="min-h-[44px] rounded-full bg-[#F5F5F6] px-4 py-2 text-sm font-medium text-gray-700 transition-colors hover:bg-gray-200/70 disabled:cursor-not-allowed disabled:opacity-50"
                onClick={closeFinalizeModal}
              >
                Cancel
              </button>
              <button
                type="button"
                disabled={
                  finalizing ||
                  Object.values(checklist).filter(Boolean).length !== 5
                }
                className="inline-flex items-center gap-2 rounded-full bg-[var(--ink)] px-6 py-3 text-sm font-semibold text-white transition-opacity hover:opacity-90 disabled:cursor-not-allowed disabled:opacity-50"
                onClick={() => void submitFinalize()}
              >
                {finalizing && (
                  <Loader2 className="h-4 w-4 animate-spin" />
                )}
                {finalizing ? "Finalizing..." : "Finalize"}
              </button>
            </div>
          </div>
        </div>
      )}

      {/* Toasts */}
      <div className="pointer-events-none fixed bottom-24 right-4 z-[60] flex max-w-sm flex-col gap-2 sm:bottom-6">
        {toasts.map((t, i) => (
          <div
            key={t.id}
            style={{ transitionDelay: `${i * 40}ms` }}
            className={`pointer-events-auto rounded-xl px-4 py-2 text-[13px] transition-opacity duration-150 ${
              t.type === "success" ? "bg-gray-900 text-white" : "bg-red-600 text-white"
            }`}
          >
            {t.message}
          </div>
        ))}
      </div>
    </div>
  );
}
