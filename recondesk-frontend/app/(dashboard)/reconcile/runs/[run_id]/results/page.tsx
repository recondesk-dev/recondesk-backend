"use client";

import { Check, ChevronDown, FileSpreadsheet, FileText, Info, Loader2, Shield, Trash2, X } from "lucide-react";
import {
  Rule37MarkPaidModal,
  type Rule37MarkPaidTarget,
} from "@/components/reconcile/Rule37MarkPaidModal";
import { ReconcilePaginationFooter } from "@/components/reconcile/ReconcilePaginationFooter";
import { Rule37SummarySection } from "@/components/reconcile/Rule37SummarySection";
import type { Rule37SummaryResponse } from "@/lib/rule37Summary";
import { SupplierFollowupAuditLogPanel } from "@/components/reconcile/SupplierFollowupAuditLogPanel";
import { Gstr3bCheckPanel } from "@/components/reconcile/Gstr3bCheckPanel";
import { SupplierFollowupLetterModal } from "@/components/reconcile/SupplierFollowupLetterModal";
import { GstinCell } from "@/components/ui/GstinCell";
import { HoverTextCell } from "@/components/ui/HoverTextCell";
import Link from "next/link";
import { useParams, useRouter } from "next/navigation";
import {
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
} from "react";
import useSWR from "swr";
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
import { apiFetch } from "@/lib/api";
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
  formatTaxDifferenceDisplay,
} from "@/lib/format";
import { useAccessToken } from "@/lib/hooks/useAccessToken";

const API_URL = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

// ─── Types ─────────────────────────────────────────────────────────────────

type MatchLevel = "EXACT" | "FUZZY" | "MANUAL" | "UNMATCHED";
type DecisionStatus = "pending" | "acted" | "ignored";
type DecisionType = "claim" | "follow_up" | "escalate" | "ignore" | null;
type Rule37Urgency = "CRITICAL" | "HIGH" | "MEDIUM";
type Rule37ActionStatus = "resolved" | "acknowledged";

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
  invoice_amount?: number;
  rule37_payment_coverage?: "full" | "partial" | null;
  section_17_5_category?: string;
};

type RunSummary = {
  run_id: string;
  client_name: string;
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
  purchase_value_at_risk_paise?: number;
  late_match_count?: number | null;
  match_rate_percent: number;
  match_rate_pct?: number;        // alias for match_rate_percent
  user_role: "admin" | "staff";
  /** PR rows excluded from matching (e.g. missing invoice number). */
  pr_skipped_count?: number;
  pr_skipped_detail?: string | null;
};

/** Shared action button styles for results header / exports */
const actionBtnBase =
  "inline-flex h-9 items-center justify-center gap-2 text-[13px] font-medium transition-colors disabled:cursor-not-allowed disabled:opacity-50";
const exportToolbarBtn = `${actionBtnBase} rounded-lg border border-[#E8E8EC] bg-white px-3 text-gray-600 hover:bg-gray-50`;
const deleteRunBtn = `${actionBtnBase} rounded-lg border border-[#E8E8EC] bg-white px-3.5 text-gray-600 hover:border-red-200 hover:bg-red-50 hover:text-red-600`;

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

function buildMatchedQuery(
  page: number,
  limit: number,
  search: string,
  f: {
    match_level: string;
    has_notes: boolean;
    section_17_5: boolean;
    amount_min: string;
    amount_max: string;
    /** When true, forces review_required=true in the query (Review Required tab). */
    force_review_required?: boolean;
  }
): string {
  const p = new URLSearchParams();
  p.set("page", String(page));
  p.set("limit", String(limit));
  p.set("sort", "amount_desc");
  const q = search.trim();
  if (q) p.set("search", q);
  if (f.match_level) p.set("match_level", f.match_level);
  if (f.has_notes) p.set("has_notes", "true");
  if (f.force_review_required) p.set("review_required", "true");
  if (f.section_17_5) p.set("section_17_5", "true");
  if (f.amount_min.trim()) p.set("amount_min", f.amount_min.trim());
  if (f.amount_max.trim()) p.set("amount_max", f.amount_max.trim());
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
  }
): boolean {
  return (
    !!search.trim() ||
    !!f.match_level ||
    f.has_notes ||
    f.section_17_5 ||
    !!f.amount_min.trim() ||
    !!f.amount_max.trim()
  );
}

type ItcFiltersState = {
  amount_min: string;
  amount_max: string;
  supplier_gstin: string;
  date_from: string;
  date_to: string;
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
  const map: Record<MatchLevel, string> = {
    EXACT: "bg-gray-100 text-gray-600",
    FUZZY: "bg-amber-50 text-amber-600",
    MANUAL: "bg-gray-100 text-gray-600",
    UNMATCHED: "bg-red-50 text-red-600",
  };
  return (
    <span
      className={`inline-flex rounded-full px-2 py-0.5 text-[11px] font-medium ${map[level]}`}
    >
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

  useEffect(() => {
    console.log("[results] tokenState:", tokenState === null ? "null (loading)" : tokenState === false ? "false (no session)" : `"${String(tokenState).slice(0, 20)}..."`);
  }, [tokenState]);

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
  const [section17Page, setSection17Page] = useState(1);

  const [resultsTab, setResultsTab] = useState<ResultsBucketTabId>("matched");
  const [rule37Open, setRule37Open] = useState(false);
  const [section17Open, setSection17Open] = useState(false);

  useEffect(() => {
    if (resultsTab === "rule37") {
      setRule37Open(true);
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
  });

  const [reviewRequiredFilters, setReviewRequiredFilters] = useState({
    match_level: "",
    has_notes: false,
    section_17_5: false,
    amount_min: "",
    amount_max: "",
  });

  useEffect(() => {
    setMatchedPage(1);
  }, [debouncedMatchedSearch, matchedFilters, matchedPageSize]);

  useEffect(() => {
    setReviewRequiredPage(1);
  }, [debouncedReviewRequiredSearch, reviewRequiredFilters, reviewRequiredPageSize]);

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

  const [itcFilters, setItcFilters] = useState<ItcFiltersState>({
    amount_min: "",
    amount_max: "",
    supplier_gstin: "",
    date_from: "",
    date_to: "",
  });
  const [debouncedItcFilters, setDebouncedItcFilters] =
    useState<ItcFiltersState>(itcFilters);
  useEffect(() => {
    const h = window.setTimeout(() => setDebouncedItcFilters(itcFilters), 400);
    return () => window.clearTimeout(h);
  }, [itcFilters]);

  const [itcSort, setItcSort] = useState("amount_desc");

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

  const [riskSort, setRiskSort] = useState("amount_desc");

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

  const isRunFinalized = Boolean(
    summary &&
      (summary.status === "final" || summary.status === "FINAL")
  );

  const downloadPdfReport = useCallback(async () => {
    if (!authToken || !runId || !summary) return;
    setPdfDownloading(true);
    try {
      const dataset = await fetchReconciliationReportData(
        authToken,
        runId,
        summary
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
  }, [addToast, authToken, runId, summary]);

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
    if (!authReady || !runId || !summary || summary.missed_itc_count <= 0)
      return null;
    return [
      `/api/reconcile/runs/${runId}/itc?${itcListQuery}`,
      authToken,
    ] as const;
  }, [authReady, runId, summary, itcListQuery, authToken]);

  const {
    data: itcPageData,
    error: itcError,
    isLoading: itcLoading,
    mutate: mutateItc,
  } = useSWR<Paginated<ReconcileRow>>(itcListKey, authJsonFetcher, {
    revalidateOnFocus: false,
  });

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
    if (!authReady || !runId || !summary || summary.wrongful_risk_count <= 0)
      return null;
    return [
      `/api/reconcile/runs/${runId}/risk?${riskListQuery}`,
      authToken,
    ] as const;
  }, [authReady, runId, summary, riskListQuery, authToken]);

  const {
    data: riskPageData,
    error: riskError,
    isLoading: riskLoading,
    mutate: mutateRisk,
  } = useSWR<Paginated<ReconcileRow>>(riskListKey, authJsonFetcher, {
    revalidateOnFocus: false,
  });

  const duplicateEntryListKey = useMemo(() => {
    if (!authReady || !runId || !summary || (summary.duplicate_entry_count ?? 0) <= 0)
      return null;
    return [
      `/api/reconcile/results/${runId}/invoices?category=duplicate_entry&page=1&page_size=100`,
      authToken,
    ] as const;
  }, [authReady, runId, summary, authToken]);

  const {
    data: duplicateEntryData,
    error: duplicateEntryError,
    isLoading: duplicateEntryLoading,
  } = useSWR<{
    invoices: Array<{
      id: string;
      supplier_gstin: string;
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

  const lateMatchesKey = useMemo(
    () =>
      authReady &&
      runId &&
      summary &&
      typeof summary.late_match_count === "number" &&
      summary.late_match_count > 0
        ? ([`/api/reconcile/runs/${runId}/late-matches`, authToken] as const)
        : null,
    [authReady, runId, summary?.late_match_count, authToken]
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
        matchedFilters
      ),
    [matchedPage, matchedPageSize, debouncedMatchedSearch, matchedFilters]
  );

  const matchedKey = useMemo(
    () =>
      authReady && runId
        ? ([`/api/reconcile/runs/${runId}/matched?${matchedQuery}`, authToken] as const)
        : null,
    [authReady, runId, matchedQuery, authToken]
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
        { ...reviewRequiredFilters, force_review_required: true }
      ),
    [reviewRequiredPage, reviewRequiredPageSize, debouncedReviewRequiredSearch, reviewRequiredFilters]
  );

  const reviewRequiredKey = useMemo(
    () =>
      authReady && runId
        ? ([`/api/reconcile/runs/${runId}/matched?${reviewRequiredQuery}`, authToken] as const)
        : null,
    [authReady, runId, reviewRequiredQuery, authToken]
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
            `/api/reconcile/runs/${runId}/section17?page=${section17Page}&limit=50`,
            authToken,
          ] as const)
        : null,
    [authReady, runId, section17Page, authToken, section17Open]
  );

  const {
    data: section17Data,
    error: section17Error,
    isLoading: section17Loading,
    mutate: mutateSection17,
  } = useSWR<Paginated<ReconcileRow>>(section17ListKey, authJsonFetcher, {
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
  } = useSWR<Note[]>(notesKey, authJsonFetcher, {
    revalidateOnFocus: false,
  });

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
    if (!text || !activeRecord || !authToken) return;
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
      const created = await apiFetch<Note>(`/api/notes/${activeRecord.id}`, {
        method: "POST",
        token: authToken,
        body: JSON.stringify({ note_text: text }),
      });
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
  }, [activeRecord, authToken, mutateDrawerNotes, mutateMatched, newNoteText]);

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
    if (!riskRows.length) return [];
    const m = new Map<
      string,
      { gstin: string; tradeName: string; count: number; total: number }
    >();
    for (const row of riskRows) {
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
  }, [riskRows, summary?.wrongful_risk_total_amount]);

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

  const unresolvedRule37Count = useMemo(() => {
    const rows = rule37Data?.data ?? [];
    return rows.filter((row) => {
      const status =
        localRule37ActionStatus.get(row.id) ?? row.rule37_action_status;
      return status !== "resolved" && status !== "acknowledged";
    }).length;
  }, [localRule37ActionStatus, rule37Data?.data]);

  const finalizeBarVisible =
    summary?.user_role === "admin" && !isRunFinalized;
  const staffFinalizeMessageVisible =
    summary?.user_role === "staff" && !isRunFinalized;

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
    if (!runId || !authToken || deleting) return;
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
  }, [authToken, deleting, runId, router]);

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
      <div className="box-border -mx-8 -mt-8 flex min-h-[60vh] flex-col items-center justify-center bg-white px-8">
        <Loader2 className="mb-4 h-10 w-10 animate-spin text-[#7B5CFA]" />
        <p className="text-base font-medium text-gray-900">
          {summary?.status_message?.trim() ||
            "Running reconciliation... This usually takes 20–40 seconds."}
        </p>
      </div>
    );
  }

  if (isRunFailed && summary && !summaryError) {
    return (
      <div className="box-border -mx-8 -mt-8 min-h-screen min-w-0 w-[calc(100%+4rem)] max-w-[calc(100%+4rem)] overflow-x-hidden bg-white px-8 py-10">
        <SectionError
          message={runFailMsg}
          onRetry={() => void mutateSummary()}
        />
      </div>
    );
  }

  return (
    <div className="box-border -mx-8 -mt-8 min-h-screen min-w-0 w-[calc(100%+4rem)] max-w-[calc(100%+4rem)] overflow-x-hidden bg-white pb-32">
      <div
        ref={summaryRef}
        className="sticky top-0 z-40 box-border w-full min-w-0 overflow-x-hidden border-b border-[#EFEFF2] bg-white/95 px-8 py-5 backdrop-blur-sm"
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
          <>
            <div className="flex w-full flex-wrap items-center justify-between gap-3">
              <div className="min-w-0 shrink">
                <p className="text-[15px] font-semibold tracking-tight text-gray-900">{summary.period}</p>
                <p className="mt-0.5 text-[12px] text-gray-500">
                  Assigned to:{" "}
                  {summary.assigned_to_name?.trim() ? (
                    summary.assigned_to_name
                  ) : (
                    <span className="italic text-gray-400">Unassigned</span>
                  )}
                </p>
                {isRunFinalized &&
                  summary.finalized_by_name &&
                  summary.finalized_at && (
                    <span className="mt-2 inline-flex rounded-md bg-green-50 px-2 py-0.5 text-[11px] font-medium text-green-700">
                      Finalized by {summary.finalized_by_name} on{" "}
                      {formatDate(summary.finalized_at)}
                    </span>
                  )}
              </div>

              <div className="flex shrink-0 items-center gap-2">
                <div
                  className="inline-flex items-center rounded-lg border border-[#E8E8EC] bg-white p-0.5"
                  role="group"
                  aria-label="Export reports"
                >
                  <button
                    type="button"
                    disabled={excelDownloading}
                    className={exportToolbarBtn}
                    onClick={() => void downloadExcelReport()}
                  >
                    {excelDownloading ? (
                      <Loader2 className="h-4 w-4 shrink-0 animate-spin text-gray-400" />
                    ) : (
                      <FileSpreadsheet className="h-4 w-4 shrink-0 text-gray-500" />
                    )}
                    Excel
                  </button>
                </div>
                <button
                  type="button"
                  className={deleteRunBtn}
                  onClick={() => {
                    setDeleteError(null);
                    setDeleteModalOpen(true);
                  }}
                >
                  <Trash2 className="h-4 w-4 shrink-0" />
                  Delete run
                </button>
              </div>
            </div>

            {(summary.pr_skipped_count ?? 0) > 0 ? (
              <div
                className="mt-3 rounded-lg border border-amber-300 bg-amber-50 px-3 py-2 text-sm text-amber-950"
                role="status"
              >
                {summary.pr_skipped_detail?.trim() ||
                  `${summary.pr_skipped_count!.toLocaleString("en-IN")} skipped: missing invoice number`}
                . These purchase register rows were not matched to GSTR-2B.
              </div>
            ) : null}

            <div className={resultsSummaryGridClass}>
              <StatCard
                label="Total GSTR"
                value={summary.total_gstr_records.toLocaleString("en-IN")}
                emphasis="secondary"
              />
              <StatCard
                label="Matched"
                accent="matched"
                value={(summary.clean_matched_count ?? summary.matched_count).toLocaleString("en-IN")}
                subtext="Clean matched"
                title={`Total linked (matched + review): ${((summary.clean_matched_count ?? summary.matched_count) + (summary.review_required_count ?? 0)).toLocaleString("en-IN")} · Unresolved: ${(summary.total_gstr_records - ((summary.clean_matched_count ?? summary.matched_count) + (summary.review_required_count ?? 0))).toLocaleString("en-IN")}`}
              />
              <StatCard
                label="Review Required"
                accent="review_required"
                value={(summary.review_required_count ?? 0).toLocaleString("en-IN")}
                subtext="Needs verification"
                emphasis="attention"
              />
              <StatCard
                label={itcHasCdnRows ? "Net 2B Difference" : "Missed ITC"}
                accent="missed"
                emphasis="danger"
                value={
                  isProcessing ? (
                    <span className="text-[clamp(1.125rem,2.1vw,1.625rem)] font-semibold tabular-nums text-gray-300">
                      —
                    </span>
                  ) : (
                    <CompactStatAmount
                      amount={summary.missed_itc_total_amount}
                      emphasize
                      className="text-red-700"
                    />
                  )
                }
              />
              <StatCard
                label="ITC at Risk"
                accent="risk"
                emphasis="danger"
                value={
                  isProcessing ? (
                    <span className="text-[clamp(1.125rem,2.1vw,1.625rem)] font-semibold tabular-nums text-gray-300">
                      —
                    </span>
                  ) : (
                    <CompactStatAmount
                      amount={summary.wrongful_risk_total_amount}
                      emphasize
                      className="text-amber-800"
                    />
                  )
                }
              />
            </div>
          </>
        )}
        {summary && !summaryError && (() => {
          const cleanCount = summary.clean_matched_count ?? summary.matched_count;
          const reviewCount = summary.review_required_count ?? 0;
          const totalLinked = cleanCount + reviewCount;
          const total = summary.total_gstr_records || 1;
          const cleanPct = Math.round((cleanCount / total) * 1000) / 10;
          const linkedPct = Math.round((totalLinked / total) * 1000) / 10;
          return (
            <div className="mt-4 space-y-2">
              {/* Clean match rate bar */}
              <div className="flex w-full items-center gap-3">
                <div className="min-w-0 flex-1 overflow-hidden">
                  <div className="h-1 w-full overflow-hidden rounded-full bg-[#ECECF0]">
                    <div
                      className="h-1 max-w-full rounded-full bg-brand transition-all duration-150"
                      style={{ width: `${Math.min(100, Math.max(0, cleanPct))}%` }}
                    />
                  </div>
                </div>
                <p className="shrink-0 whitespace-nowrap text-[11px] text-gray-400">
                  Clean Match Rate
                </p>
              </div>
              {/* Total linked rate bar */}
              <div className="flex w-full items-center gap-3">
                <div className="min-w-0 flex-1 overflow-hidden">
                  <div className="h-1 w-full overflow-hidden rounded-full bg-[#ECECF0]">
                    <div
                      className="h-1 max-w-full rounded-full bg-[#7B5CFA] transition-all duration-150"
                      style={{ width: `${Math.min(100, Math.max(0, linkedPct))}%` }}
                    />
                  </div>
                </div>
                <p className="shrink-0 whitespace-nowrap text-[11px] text-gray-400">
                  Total Linked Rate
                </p>
              </div>
              {/* Combined label */}
              <div className="flex items-center gap-2">
                <span className="inline-flex items-center gap-1 rounded-md bg-brand/10 px-2 py-0.5 text-[11px] font-medium text-brand">
                  {cleanPct}% clean
                </span>
                <span className="text-[11px] text-gray-300">·</span>
                <span className="inline-flex items-center gap-1 rounded-md bg-[#7B5CFA]/10 px-2 py-0.5 text-[11px] font-medium text-[#7B5CFA]">
                  {linkedPct}% linked
                </span>
              </div>
            </div>
          );
        })}
      </div>

      <div className={pageContentClass}>
        {summary && (
          <ResultsBucketTabs
            active={resultsTab}
            onChange={setResultsTab}
            tabCounts={{
              matched: summary.clean_matched_count ?? summary.matched_count,
              review_required: summary.review_required_count ?? 0,
              duplicate_entry: summary.duplicate_entry_count ?? 0,
              risk: summary.wrongful_risk_count ?? 0,
              itc: summary.missed_itc_count ?? 0,
            }}
            rightContent={
              <button
                type="button"
                disabled={pdfDownloading || !summary}
                className="inline-flex h-9 items-center justify-center gap-2 rounded-lg border border-[#E8E8EC] bg-white px-3.5 text-[13px] font-medium text-gray-700 hover:bg-gray-50 transition-colors disabled:cursor-not-allowed disabled:opacity-50"
                onClick={() => void downloadPdfReport()}
              >
                {pdfDownloading ? (
                  <Loader2 className="h-4 w-4 shrink-0 animate-spin text-[#7B5CFA]" />
                ) : (
                  <FileText className="h-4 w-4 shrink-0 text-[#7B5CFA]" />
                )}
                Download Reconciliation Report (PDF)
              </button>
            }
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
                  value={itcSort}
                  onChange={(e) => setItcSort(e.target.value)}
                >
                  <option value="amount_desc">ITC Amount ↓</option>
                  <option value="amount_asc">ITC Amount ↑</option>
                  <option value="supplier_name">Supplier Name</option>
                  <option value="invoice_date">Invoice Date</option>
                </select>
                {(hasActiveItcFilters(itcFilters) || !!docTypeFilterItc) && (
                  <button
                    type="button"
                    className="h-9 text-[13px] font-medium text-brand hover:underline"
                    onClick={() => {
                      setDocTypeFilterItc("");
                      setItcFilters({
                        amount_min: "",
                        amount_max: "",
                        supplier_gstin: "",
                        date_from: "",
                        date_to: "",
                      });
                    }}
                  >
                    Clear filters
                  </button>
                )}
              </div>
            </div>

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
                      className="text-[13px] font-medium text-brand hover:underline"
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
                <div className={decisionTableWrapClass}>
                  <table className={decisionTableClass}>
                    <DecisionTableColGroup />
                    <thead className={tableHeadClass}>
                      <tr>
                        <th className={tableStickyCheckboxHeadClass}>
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
                                if (on)
                                  itcRows.forEach((r) => next.itc.add(r.id));
                                else
                                  itcRows.forEach((r) => next.itc.delete(r.id));
                                return next;
                              });
                            }}
                            className="rounded border-gray-300"
                          />
                        </th>
                        <th className={decisionTh("num")}>#</th>
                        <th className={decisionTh("gstin")}>Supplier GSTIN</th>
                        <th className={decisionTh("invoice")}>Invoice#</th>
                        <th className={decisionTh("date")}>Date</th>
                        <th className={decisionTh("amount", "right")}>Amount</th>
                        <th className={decisionTh("impact")}>Impact</th>
                        <th className={decisionTh("what")}>WHAT</th>
                        <th className={decisionTh("why")}>WHY</th>
                        <th className={decisionTh("next")}>NEXT</th>
                        <th className={decisionTh("status")}>Match Status</th>
                      </tr>
                    </thead>
                    <tbody>
                      {itcRows.filter(r => checkDocType(r, docTypeFilterItc)).map((row, i) => (
                        <tr key={row.id} className={`group ${tableRowClass}`}>
                          <td className={tableStickyCheckboxCellClass}>
                            <input
                              type="checkbox"
                              disabled={isRunFinalized}
                              checked={selectedIds.itc.has(row.id)}
                              onChange={(e) => {
                                setSelectedIds((prev) => {
                                  const next = {
                                    ...prev,
                                    itc: new Set(prev.itc),
                                  };
                                  if (e.target.checked) next.itc.add(row.id);
                                  else next.itc.delete(row.id);
                                  return next;
                                });
                              }}
                              className="rounded border-gray-300"
                            />
                          </td>
                          <td className={`${decisionTd("num")} text-[13px] text-gray-500`}>
                            {(itcPage - 1) * itcPageData.limit + i + 1}
                          </td>
                          <td className={`${decisionTd("gstin")} font-mono text-[13px] text-gray-500`}>
                            <GstinCell gstin={row.supplier_gstin} />
                          </td>
                          <td className={decisionTd("invoice")}>
                            <HoverTextCell
                              text={row.invoice_number}
                              displayClassName="text-[13px] font-medium text-gray-800"
                            />
                          </td>
                          <td className={`${decisionTd("date")} text-[13px] text-gray-500`}>
                            {formatDate(row.invoice_date)}
                          </td>
                          <td className={decisionTd("amount")}>
                            <AmountDisplay amount={row.amount} />
                          </td>
                          <td className={decisionTd("impact")}>
                            <ImpactBadge
                              level={getImpactLevel(row.amount, itcMax)}
                            />
                          </td>
                          <td className={decisionTd("what")}>
                            <HoverTextCell
                              text={row.decision_what}
                              displayClassName="text-[13px] text-gray-600"
                            />
                          </td>
                          <td className={decisionTd("why")}>
                            <HoverTextCell
                              text={row.decision_why}
                              displayClassName="text-[13px] italic text-gray-400"
                            />
                          </td>
                          <td className={decisionTd("next")}>
                            <HoverTextCell
                              text={row.decision_next}
                              displayClassName="text-[13px] font-medium text-brand"
                            />
                          </td>
                          <td className={decisionTd("status")}>
                            <div className="flex flex-col gap-1.5">
                              <div>
                                <span className="inline-flex">
                                  <DecisionStatusPill status={effectiveStatus(row)} />
                                </span>
                              </div>
                              {effectiveStatus(row) === "pending" && (
                                <div className="text-[11px] font-medium text-[#6B7280]">
                                  {row.discrepancy_note || "Review required"}
                                </div>
                              )}
                            </div>
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
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
              title="ITC at Risk — Not Reflected in GSTR-2B"
              dotColor="#DC2626"
              badges={[
                {
                  label: "TOTAL ITC AT RISK",
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
                Top Suppliers by ITC at Risk
              </h3>
              {riskLoading && !riskPageData && (
                <div className="animate-pulse space-y-2 py-2">
                  <div className="h-8 rounded bg-gray-100" />
                  <div className="h-8 rounded bg-gray-100/90" />
                  <div className="h-8 rounded bg-gray-100/80" />
                </div>
              )}
              {!(riskLoading && !riskPageData) &&
                topSuppliersByRisk.length === 0 && (
                  <p className="text-sm text-gray-500">
                    No supplier risk data available.
                  </p>
                )}
              {!(riskLoading && !riskPageData) &&
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
                              Total ITC at Risk
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
                        className="text-[13px] font-medium text-brand hover:underline"
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
                  className={filterDropdownClass}
                  value={riskSort}
                  onChange={(e) => setRiskSort(e.target.value)}
                >
                  <option value="amount_desc">ITC at Risk ↓</option>
                  <option value="amount_asc">ITC at Risk ↑</option>
                  <option value="supplier_name">Supplier Name</option>
                  <option value="invoice_date">Invoice Date</option>
                </select>
                {(hasActiveRiskFilters(riskFilters) || !!docTypeFilterRisk) && (
                  <button
                    type="button"
                    className="h-9 text-[13px] font-medium text-brand hover:underline"
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
                      className="rounded-lg border border-brand/30 bg-brand/5 px-3 py-1.5 text-[13px] font-medium text-brand hover:bg-brand/10 disabled:cursor-not-allowed disabled:opacity-50"
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
                      className="text-[13px] font-medium text-brand hover:underline"
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
                    title="No ITC-at-risk rows for this filter"
                    description="Adjust amount, GSTIN, or risk level filters to see compliance risk invoices."
                  />
                ) : (
                <div className={decisionTableWrapClass}>
                  <table className={decisionTableClass}>
                    <DecisionTableColGroup includeNotice />
                    <thead className={tableHeadClass}>
                      <tr>
                        <th className={tableStickyCheckboxHeadClass}>
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
                                if (on)
                                  riskRows.forEach((r) => next.risk.add(r.id));
                                else
                                  riskRows.forEach((r) =>
                                    next.risk.delete(r.id)
                                  );
                                return next;
                              });
                            }}
                            className="rounded border-gray-300"
                          />
                        </th>
                        <th className={decisionTh("num")}>#</th>
                        <th className={decisionTh("gstin")}>Supplier GSTIN</th>
                        <th className={decisionTh("invoice")}>Invoice#</th>
                        <th className={decisionTh("date")}>Date</th>
                        <th className={decisionTh("amount", "right")}>
                          ITC at Risk
                        </th>
                        <th className={decisionTh("impact")}>Impact</th>
                        <th className={decisionTh("what")}>WHAT</th>
                        <th className={decisionTh("why")}>WHY</th>
                        <th className={decisionTh("next")}>NEXT</th>
                        <th className={decisionTh("status")}>Match Status</th>
                        <th className={decisionTh("notice", "right")}>
                          Follow-up
                        </th>
                      </tr>
                    </thead>
                    <tbody>
                      {riskRows.filter(r => checkDocType(r, docTypeFilterRisk)).map((row, i) => (
                        <tr key={row.id} className={`group ${tableRowClass}`}>
                          <td className={tableStickyCheckboxCellClass}>
                            <input
                              type="checkbox"
                              disabled={isRunFinalized}
                              checked={selectedIds.risk.has(row.id)}
                              onChange={(e) => {
                                setSelectedIds((prev) => {
                                  const next = {
                                    ...prev,
                                    risk: new Set(prev.risk),
                                  };
                                  if (e.target.checked) next.risk.add(row.id);
                                  else next.risk.delete(row.id);
                                  return next;
                                });
                              }}
                              className="rounded border-gray-300"
                            />
                          </td>
                          <td className={`${decisionTd("num")} text-[13px] text-gray-500`}>
                            {(riskPage - 1) * riskPageData.limit + i + 1}
                          </td>
                          <td className={`${decisionTd("gstin")} font-mono text-[13px] text-gray-500`}>
                            <GstinCell gstin={row.supplier_gstin} />
                          </td>
                          <td className={decisionTd("invoice")}>
                            <HoverTextCell
                              text={row.invoice_number}
                              displayClassName="text-[13px] font-medium text-gray-800"
                            />
                          </td>
                          <td className={`${decisionTd("date")} text-[13px] text-gray-500`}>
                            {formatDate(row.invoice_date)}
                          </td>
                          <td className={decisionTd("amount")}>
                            <AmountDisplay amount={row.amount} />
                          </td>
                          <td className={decisionTd("impact")}>
                            <ImpactBadge
                              level={getImpactLevel(row.amount, riskMax)}
                            />
                          </td>
                          <td className={decisionTd("what")}>
                            <HoverTextCell
                              text={row.decision_what}
                              displayClassName="text-[13px] text-gray-600"
                            />
                          </td>
                          <td className={decisionTd("why")}>
                            <HoverTextCell
                              text={row.decision_why}
                              displayClassName="text-[13px] italic text-gray-400"
                            />
                          </td>
                          <td className={decisionTd("next")}>
                            <HoverTextCell
                              text={row.decision_next}
                              displayClassName="text-[13px] font-medium text-brand"
                            />
                          </td>
                          <td className={decisionTd("status")}>
                            <div className="flex flex-col gap-1.5">
                              <div>
                                <span className="inline-flex">
                                  <DecisionStatusPill status={effectiveStatus(row)} />
                                </span>
                              </div>
                              {effectiveStatus(row) === "pending" && (
                                <div className="text-[11px] font-medium text-[#6B7280]">
                                  {row.discrepancy_note || "Review required"}
                                </div>
                              )}
                            </div>
                          </td>
                          <td className={decisionTd("notice", { align: "right" })}>
                            <button
                              type="button"
                              disabled={isRunFinalized || !authToken}
                              className="max-w-full rounded-lg border border-[#E5E7EB] bg-white px-2 py-1.5 text-[10px] font-medium leading-tight text-brand hover:bg-brand/5 disabled:cursor-not-allowed disabled:opacity-50"
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
          </div>
        )}

        {summary &&
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
        <div className={sectionContainerClass}>
          <h2 className="mb-1 text-[15px] font-semibold tracking-tight text-gray-900">
            Matched{" "}
            {summary != null && (
              <span className="font-normal text-gray-500">
                ({(summary.clean_matched_count ?? summary.matched_count).toLocaleString("en-IN")})
              </span>
            )}
          </h2>
          {/* Requirement 4: info line */}
          <p className="mb-5 text-[12px] leading-relaxed text-gray-500">
            Showing auto-matched records with no discrepancies. Records requiring review are in the{" "}
            <button
              type="button"
              className="font-medium text-[#D97706] hover:underline"
              onClick={() => setResultsTab("review_required")}
            >
              Review Required tab
            </button>
            .
          </p>

          <div className={filterToolbarClass}>
            <input
              type="search"
              className={`w-full ${filterInputClass}`}
              placeholder="Search by supplier GSTIN or invoice number..."
              value={matchedSearch}
              onChange={(e) => setMatchedSearch(e.target.value)}
            />
            <div className={filterRowClass}>
              <select
                className={filterDropdownClass}
                value={docTypeFilterMatched}
                onChange={(e) => setDocTypeFilterMatched(e.target.value)}
              >
                <option value="">All Document Types</option>
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
              <input
                className={filterAmountInputClass}
                placeholder="₹ Min"
                value={matchedFilters.amount_min}
                onChange={(e) =>
                  setMatchedFilters((f) => ({
                    ...f,
                    amount_min: e.target.value,
                  }))
                }
              />
              <input
                className={filterAmountInputClass}
                placeholder="₹ Max"
                value={matchedFilters.amount_max}
                onBlur={() => setMatchedPage(1)}
                onChange={(e) =>
                  setMatchedFilters((f) => ({
                    ...f,
                    amount_max: e.target.value,
                  }))
                }
              />
              <button
                type="button"
                className={`${filterToggleClass} ${
                  matchedFilters.has_notes
                    ? filterToggleActiveClass
                    : filterToggleIdleClass
                }`}
                onClick={() =>
                  setMatchedFilters((f) => ({
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
                  matchedFilters.section_17_5
                    ? "border-gray-800 bg-gray-900/[0.04] text-gray-800"
                    : filterToggleIdleClass
                }`}
                onClick={() =>
                  setMatchedFilters((f) => ({
                    ...f,
                    section_17_5: !f.section_17_5,
                  }))
                }
              >
                Section 17(5)
              </button>
              {(hasActiveMatchedFilters(debouncedMatchedSearch, matchedFilters) || !!docTypeFilterMatched) && (
                <button
                  type="button"
                  className="h-9 text-[13px] font-medium text-brand hover:underline"
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
                    });
                    setMatchedPage(1);
                  }}
                >
                  Clear all filters
                </button>
              )}
            </div>
            
            {summary && (
              <div className="flex flex-wrap items-center gap-2 text-[13px] font-medium w-fit">
                <button
                  type="button"
                  onClick={() => setMatchedFilters((f) => ({
                    ...f,
                    match_level: f.match_level === "EXACT" ? "" : "EXACT"
                  }))}
                  className={`flex h-8 items-center gap-2 rounded-full border px-3 text-[12px] transition-colors ${
                    matchedFilters.match_level === "EXACT" 
                      ? "bg-[#22C55E]/10 border-[#22C55E]/30 text-[#22C55E]" 
                      : "bg-white border-[#E8E8EC] text-gray-600 hover:bg-gray-50"
                  }`}
                >
                  <span className={`h-1.5 w-1.5 shrink-0 rounded-full ${matchedFilters.match_level === "EXACT" ? "bg-[#22C55E]" : "bg-gray-300"}`} aria-hidden />
                  {(summary?.clean_matched_count ?? summary?.matched_count ?? 0).toLocaleString("en-IN")} Matched
                </button>
                <button
                  type="button"
                  onClick={() => setMatchedFilters((f) => ({
                    ...f,
                    match_level: f.match_level === "FUZZY" ? "" : "FUZZY"
                  }))}
                  className={`flex h-8 items-center gap-2 rounded-full border px-3 text-[12px] transition-colors ${
                    matchedFilters.match_level === "FUZZY" 
                      ? "bg-[#F59E0B]/10 border-[#F59E0B]/30 text-[#F59E0B]" 
                      : "bg-white border-[#E8E8EC] text-gray-600 hover:bg-gray-50"
                  }`}
                >
                  <span className={`h-1.5 w-1.5 shrink-0 rounded-full ${matchedFilters.match_level === "FUZZY" ? "bg-[#F59E0B]" : "bg-gray-300"}`} aria-hidden />
                  {((summary?.clean_matched_count ?? summary?.matched_count ?? 0) - (summary?.exact_match_count ?? 0)).toLocaleString("en-IN")} Non-exact match
                </button>
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
            <div className="animate-pulse space-y-2 py-4">
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
                      <th className={matchedThInvoice}>Invoice#</th>
                      <th className={matchedThDate}>Date</th>
                      <th className={matchedThAmount}>Amount</th>
                      <th className={matchedThMatchLevel}>
                        <div className="flex items-center gap-1">
                          Match Method
                          <span title="L1 = Exact GSTIN + Invoice Number match&#10;L2 = GSTIN match + fuzzy invoice number&#10;L3 = GSTIN match + amount match&#10;L4 = Fuzzy vendor name + amount match&#10;L5 = Partial / manual review needed">
                            <Info className="h-3.5 w-3.5 text-gray-400 cursor-help" />
                          </span>
                        </div>
                      </th>
                      <th className={matchedThConfidence}>Confidence</th>
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

                      // NOTE: a client-side "gstrAmt vs raw PR invoice value" recompute
                      // used to run here for FUZZY/EXACT rows. It compared row.amount
                      // (the GSTR record's total_tax_paise — the TAX portion only) against
                      // a raw "Invoice Amount"/"Total"/"Grand Total" field pulled from the
                      // uploaded Purchase Register (the FULL invoice value, taxable + tax).
                      // Those two figures are not comparable, so the "diff" it produced was
                      // effectively the PR's own invoice value, not a real discrepancy. The
                      // server-computed row.tax_difference_paise above is always the correct
                      // abs(gstr_taxable - pr_taxable) (or the ₹0/N-A discrepancy_reason
                      // fallback for non-financial mismatches), so it is used as-is.

                      return (
                      <tr
                        key={row.id}
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
                            displayClassName="text-[13px] font-medium text-gray-800"
                          />
                        </td>
                        <td className={matchedTdDate}>
                          {formatDate(row.invoice_date)}
                        </td>
                        <td className={matchedTdAmount}>
                          <AmountDisplay amount={row.amount} />
                        </td>
                        <td className={matchedTdMatchLevel}>
                          <MatchLevelBadge level={row.match_level} />
                        </td>
                        <td className={matchedTdConfidence}>
                          {Math.round(
                            Math.min(100, Math.max(0, row.confidence_score))
                          )}
                          %
                        </td>
                        <td className={matchedTdDiscrepancy}>
                          <HoverTextCell
                            text={taxDiff.display}
                            tooltipText={taxDiff.tooltip}
                            displayClassName="text-[13px] text-gray-600"
                          />
                        </td>
                        <td className={matchedTdNotes}>
                          {row.notes_count > 0 ? (
                            <span className="inline-flex rounded-full bg-gray-100 px-2 py-0.5 text-[11px] font-medium text-gray-500">
                              {row.notes_count} notes
                            </span>
                          ) : (
                            "—"
                          )}
                        </td>
                      </tr>
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
          <Gstr3bCheckPanel runId={runId} authToken={authToken} />
        )}

        {resultsTab === "followup" && authToken && (
          <SupplierFollowupAuditLogPanel runId={runId} authToken={authToken} />
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
              from GSTR-2B, and not included in ITC at Risk.
            </p>
            {(summary?.duplicate_entry_count ?? 0) <= 0 ? (
              <p className="text-sm text-gray-500">No duplicate entries in this run.</p>
            ) : duplicateEntryLoading ? (
              <p className="text-sm text-gray-500">Loading…</p>
            ) : duplicateEntryError ? (
              <p className="text-sm text-red-600">Failed to load duplicate entries.</p>
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
                    {(duplicateEntryData?.invoices ?? []).map((row) => (
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

        {/* Review Required */}
        {resultsTab === "review_required" && (
        <div className={sectionContainerClass}>
          <h2 className="mb-1 text-[15px] font-semibold tracking-tight text-gray-900">
            Review Required{" "}
            {summary != null && (
              <span className="font-normal text-gray-500">
                ({(summary.review_required_count ?? 0).toLocaleString("en-IN")})
              </span>
            )}
          </h2>
          <p className="mb-5 text-[12px] leading-relaxed text-gray-500">
            These records were matched but have discrepancies or low confidence that need manual verification before finalizing.
          </p>

          <div className={filterToolbarClass}>
            <input
              type="search"
              className={`w-full ${filterInputClass}`}
              placeholder="Search by supplier GSTIN or invoice number..."
              value={reviewRequiredSearch}
              onChange={(e) => setReviewRequiredSearch(e.target.value)}
            />
            <div className={filterRowClass}>
              <select
                className={filterDropdownClass}
                value={docTypeFilterReviewRequired}
                onChange={(e) => setDocTypeFilterReviewRequired(e.target.value)}
              >
                <option value="">All Document Types</option>
                <option value="Invoice">Invoice</option>
                <option value="Credit Note">Credit Note</option>
                <option value="Debit Note">Debit Note</option>
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
                <option value="">All levels</option>
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
                  className="h-9 text-[13px] font-medium text-brand hover:underline"
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
              <div className={tableWrapClass}>
                <table className={matchedTableClass}>
                  <thead className={tableHeadClass}>
                    <tr>
                      <th className={matchedThGstin}>Supplier GSTIN</th>
                      <th className={matchedThInvoice}>Invoice#</th>
                      <th className={matchedThDate}>Date</th>
                      <th className={matchedThAmount}>Amount</th>
                      <th className={matchedThMatchLevel}>
                        <div className="flex items-center gap-1">
                          Match Method
                          <span title="L1 = Exact GSTIN + Invoice Number match&#10;L2 = GSTIN match + fuzzy invoice number&#10;L3 = GSTIN match + amount match&#10;L4 = Fuzzy vendor name + amount match&#10;L5 = Partial / manual review needed">
                            <Info className="h-3.5 w-3.5 text-gray-400 cursor-help" />
                          </span>
                        </div>
                      </th>
                      <th className={matchedThConfidence}>Confidence</th>
                      <th className={matchedThDiscrepancy}>Discrepancy / Reason</th>
                      <th className={matchedThGuidanceWhat}>What</th>
                      <th className={matchedThGuidanceWhy}>Why</th>
                      <th className={matchedThGuidanceNext}>Next</th>
                      <th className={matchedThNotes}>Notes</th>
                    </tr>
                  </thead>
                  <tbody>
                    {(() => {
                      const validRows = reviewRequiredData.data
                        .filter(r => checkDocType(r, docTypeFilterReviewRequired))
                        .filter(r => r.supplier_gstin || r.invoice_number || (r.amount && r.amount > 0));
                      return validRows.map((row) => {
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

                      // NOTE: a client-side "gstrAmt vs raw PR invoice value" recompute
                      // used to run here for FUZZY/EXACT rows (which is most Review
                      // Required rows, since Phase-2 review reasons like GSTIN_MISMATCH,
                      // DUPLICATE_AMBIGUITY, TYPO_MISMATCH etc. all map to "FUZZY"). It
                      // compared row.amount (the GSTR record's total_tax_paise — the TAX
                      // portion only) against a raw "Invoice Amount"/"Total"/"Grand Total"
                      // field pulled from the uploaded Purchase Register (the FULL invoice
                      // value, taxable + tax). Those two figures are not comparable, so for
                      // a GSTIN-mismatch or date-shift row with an identical taxable amount
                      // on both sides, the "diff" it produced was effectively the PR's own
                      // invoice value — a large fabricated discrepancy where the real gap is
                      // ₹0. The server-computed row.tax_difference_paise above is always the
                      // correct abs(gstr_taxable - pr_taxable) for genuinely paired rows (and
                      // ₹0 when there is no counterpart to diff against), with the
                      // discrepancy_reason label shown when that diff is ₹0, so it is used
                      // as-is with no further client-side override.

                      return (
                      <tr
                        key={row.id}
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
                            displayClassName="text-[13px] font-medium text-gray-800"
                          />
                        </td>
                        <td className={matchedTdDate}>
                          {formatDate(row.invoice_date)}
                        </td>
                        <td className={matchedTdAmount}>
                          <AmountDisplay amount={row.amount} />
                        </td>
                        <td className={matchedTdMatchLevel}>
                          <MatchLevelBadge level={row.match_level} />
                        </td>
                        <td className={matchedTdConfidence}>
                          {Math.round(
                            Math.min(100, Math.max(0, row.confidence_score))
                          )}
                          %
                        </td>
                        <td className={matchedTdDiscrepancy}>
                          <HoverTextCell
                            text={taxDiff.display}
                            tooltipText={taxDiff.tooltip}
                            displayClassName="text-[13px] text-gray-600"
                          />
                        </td>
                        <td className={matchedTdGuidanceWhat}>
                          <HoverTextCell
                            text={row.decision_what}
                            displayClassName="text-[13px] text-gray-600"
                          />
                        </td>
                        <td className={matchedTdGuidanceWhy}>
                          <HoverTextCell
                            text={row.decision_why}
                            displayClassName="text-[13px] italic text-gray-400"
                          />
                        </td>
                        <td className={matchedTdGuidanceNext}>
                          <HoverTextCell
                            text={row.decision_next}
                            displayClassName="text-[13px] font-medium text-brand"
                          />
                        </td>
                        <td className={matchedTdNotes}>
                          {row.notes_count > 0 ? (
                            <span className="inline-flex rounded-full bg-amber-50 px-2 py-0.5 text-[11px] font-medium text-amber-700">
                              {row.notes_count} notes
                            </span>
                          ) : (
                            "—"
                          )}
                        </td>
                      </tr>
                    );
                    })
})()}
                  </tbody>
                </table>
              </div>
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

        {/* Rule 37 */}
        {resultsTab === "rule37" && (
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
                Rule 37 Tracking
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
                  label="AMOUNT AT RISK"
                  amount={rule37TotalAmount}
                  variant="rule37"
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
                  No Rule 37 warnings for this period.
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
                    actionStatus === "acknowledged";
                  return (
                    <div
                      key={row.id}
                      className={`mb-3 rounded-2xl border border-[#F0F0F0] border-l-4 bg-white p-5 ${rule37BorderClass(u, acted)}`}
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
                        {!acted && <Rule37SeverityLabel urgency={u} />}
                      </div>
                      <p className="mt-3 text-[13px] font-medium text-gray-700">
                        {row.decision_what ?? "—"}
                      </p>
                      <p className="mt-1 text-[13px] text-gray-400">
                        {row.decision_why ?? "—"}
                      </p>
                      <p className="mt-2 text-[13px] font-medium text-brand">
                        {row.decision_next ?? "—"}
                      </p>
                      <DecisionDiagnosticsBlock row={row} />
                      <div className="mt-4 flex flex-wrap justify-end gap-2">
                        {actionStatus === "resolved" && (
                          <span className="inline-flex items-center rounded-lg bg-gray-100 px-4 py-2 text-[13px] text-gray-400">
                            Marked as Settled ✓
                            {row.rule37_payment_coverage === "partial" ? (
                              <span className="ml-1 text-amber-600">
                                (Partial)
                              </span>
                            ) : null}
                          </span>
                        )}
                        {actionStatus === "acknowledged" && (
                          <span className="inline-flex items-center rounded-lg bg-gray-100 px-4 py-2 text-[13px] text-gray-400">
                            ITC Reversal Noted ✓
                          </span>
                        )}
                        {!acted && (
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
        )}

        {/* Section 17(5) */}
        <div className={sectionContainerClass}>
          <button
            type="button"
            className="flex w-full items-center justify-between text-left transition-all duration-150"
            onClick={() => setSection17Open((o) => !o)}
          >
            <span className="flex items-center gap-2">
              <span
                className="h-2 w-2 shrink-0 rounded-full bg-gray-400"
                aria-hidden
              />
              <span className="text-lg font-semibold text-gray-900">
                Section 17(5) — Blocked ITC Flags
                {section17Data != null && (
                  <span className="ml-2 rounded-full bg-gray-100 px-2 py-0.5 text-[11px] font-medium text-gray-500">
                    {section17Data.total}
                  </span>
                )}
              </span>
            </span>
            <ChevronDown
              className={`h-5 w-5 shrink-0 text-gray-500 transition-transform ${
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
                    className="mb-3 rounded-2xl border border-[#F0F0F0] bg-white p-5"
                  >
                    {row.section_17_5_category && (
                      <span className="mb-3 inline-block rounded-full bg-gray-100 px-2 py-0.5 text-[11px] font-medium text-gray-500">
                        {row.section_17_5_category}
                      </span>
                    )}
                    <p className="text-[13px] font-medium text-gray-700">
                      {row.decision_what ?? "—"}
                    </p>
                    <p className="mt-1 text-[13px] text-gray-400">
                      {row.decision_why ?? "—"}
                    </p>
                    <p className="mt-2 text-[13px] font-medium text-brand">
                      {row.decision_next ?? "—"}
                    </p>
                    <DecisionDiagnosticsBlock row={row} />
                  </div>
                ))}
              {section17Data &&
                !section17Error &&
                section17Data.total_pages > 1 && (
                  <ReconcilePaginationFooter
                    page={section17Data.page}
                    totalPages={section17Data.total_pages}
                    total={section17Data.total}
                    limit={section17Data.limit}
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
                <p className="mb-3 text-[13px] font-medium text-brand">
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

      {/* Finalize bar */}
      {finalizeBarVisible && (
        <div className="fixed bottom-0 left-[240px] right-0 z-40 border-t border-[#EFEFF2] bg-white/95 px-6 py-3.5 backdrop-blur-sm">
          <div className="mx-auto flex max-w-7xl flex-wrap items-center justify-between gap-4">
            <div className="flex min-w-0 items-start gap-2.5 rounded-lg border border-[#EFEFF2] bg-[#FAFAFB] px-3.5 py-2.5">
              <Check className="mt-0.5 h-3.5 w-3.5 shrink-0 text-gray-400" aria-hidden />
              <div className="min-w-0">
                <p className="text-[12px] font-medium text-gray-700">
                  Checklist before finalize
                </p>
                <p className="mt-0.5 text-[11px] leading-snug text-gray-500">
                  Review Matched, Review Required, Missed ITC, and ITC at Risk before locking this run.
                </p>
              </div>
            </div>
            <button
              type="button"
              className="inline-flex shrink-0 items-center gap-2 rounded-lg bg-brand px-5 py-2.5 text-[13px] font-semibold text-white transition-colors duration-150 hover:bg-brand-hover"
              onClick={() => setFinalizeModalOpen(true)}
            >
              Finalize Reconciliation
            </button>
          </div>
        </div>
      )}

      {staffFinalizeMessageVisible && (
        <div className="fixed bottom-0 left-[240px] right-0 z-40 border-t border-[#EFEFF2] bg-white/95 px-6 py-4 backdrop-blur-sm flex items-center justify-center">
          <p className="text-center text-[13px] text-gray-500">
            Only your CA principal (admin) can finalize this reconciliation.
          </p>
        </div>
      )}

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

      {deleteModalOpen && (
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
                      className={`mt-0.5 flex h-5 w-5 shrink-0 items-center justify-center rounded border-2 ${
                        checked
                          ? "border-brand bg-brand text-white"
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
                      className="h-1.5 rounded-full bg-brand transition-all duration-150"
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
                className="min-h-[44px] rounded-full border border-gray-300 bg-white px-4 py-2 text-sm font-medium text-gray-700 disabled:cursor-not-allowed disabled:opacity-50"
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
                className="inline-flex items-center gap-2 rounded-2xl bg-brand px-6 py-3 text-sm font-semibold text-white shadow-md shadow-brand/20 transition-all duration-150 hover:bg-brand-hover disabled:cursor-not-allowed disabled:opacity-50"
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
