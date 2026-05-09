"use client";

import { Check, ChevronDown, FileSpreadsheet, FileText, Loader2, Shield, X } from "lucide-react";
import Link from "next/link";
import { useParams } from "next/navigation";
import {
  useCallback,
  useEffect,
  useLayoutEffect,
  useMemo,
  useRef,
  useState,
} from "react";
import useSWR from "swr";
import { apiFetch } from "@/lib/api";
import { useAccessToken } from "@/lib/hooks/useAccessToken";

const API_URL = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

// ─── Types ─────────────────────────────────────────────────────────────────

type MatchLevel = "EXACT" | "FUZZY" | "MANUAL" | "UNMATCHED";
type DecisionStatus = "pending" | "acted" | "ignored";
type DecisionType = "claim" | "follow_up" | "escalate" | "ignore" | null;
type Rule37Urgency = "CRITICAL" | "HIGH" | "MEDIUM";

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
  decision_what: string | null;
  decision_why: string | null;
  decision_next: string | null;
  decision_status: DecisionStatus;
  decision_type: DecisionType;
  notes_count: number;
  gstr2b_data: Record<string, string | number>;
  purchase_register_data: Record<string, string | number>;
  rule37_urgency?: Rule37Urgency;
  section_17_5_category?: string;
};

type RunSummary = {
  run_id: string;
  client_name: string;
  period: string;
  assigned_to_name: string;
  status: string;
  finalized_by_name: string | null;
  finalized_at: string | null;
  total_gstr_records: number;
  matched_count: number;
  missed_itc_count: number;
  missed_itc_total_amount: number;
  wrongful_risk_count: number;
  wrongful_risk_total_amount: number;
  late_match_count?: number | null;
  match_rate_percent: number;
  user_role: "admin" | "staff";
};

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

function formatINR(amount: number): string {
  return amount.toLocaleString("en-IN", {
    style: "currency",
    currency: "INR",
    maximumFractionDigits: 0,
  });
}

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

type FetcherKey = readonly [path: string, token: string];

async function authJsonFetcher<T>([path, token]: FetcherKey): Promise<T> {
  return apiFetch<T>(path, { token });
}

function buildMatchedQuery(
  page: number,
  search: string,
  f: {
    match_level: string;
    has_notes: boolean;
    review_required: boolean;
    section_17_5: boolean;
    amount_min: string;
    amount_max: string;
  }
): string {
  const p = new URLSearchParams();
  p.set("page", String(page));
  p.set("limit", "50");
  p.set("sort", "amount_desc");
  const q = search.trim();
  if (q) p.set("search", q);
  if (f.match_level) p.set("match_level", f.match_level);
  if (f.has_notes) p.set("has_notes", "true");
  if (f.review_required) p.set("review_required", "true");
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
    review_required: boolean;
    section_17_5: boolean;
    amount_min: string;
    amount_max: string;
  }
): boolean {
  return (
    !!search.trim() ||
    !!f.match_level ||
    f.has_notes ||
    f.review_required ||
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
  sort: string,
  f: ItcFiltersState
): string {
  const p = new URLSearchParams();
  p.set("page", String(page));
  p.set("limit", "50");
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
  sort: string,
  f: RiskFiltersState
): string {
  const p = new URLSearchParams();
  p.set("page", String(page));
  p.set("limit", "50");
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

function DecisionStatusPill({
  status,
}: {
  status: DecisionStatus;
}) {
  if (status === "acted")
    return (
      <span className="inline-flex rounded-full bg-emerald-100 px-2 py-0.5 text-xs font-medium text-emerald-800">
        Acted
      </span>
    );
  if (status === "ignored")
    return (
      <span className="inline-flex rounded-full bg-gray-200 px-2 py-0.5 text-xs font-medium text-gray-500 line-through">
        Ignored
      </span>
    );
  return (
    <span className="inline-flex rounded-full bg-gray-100 px-2 py-0.5 text-xs font-medium text-gray-600">
      Pending
    </span>
  );
}

function MatchLevelBadge({ level }: { level: MatchLevel }) {
  const map: Record<MatchLevel, string> = {
    EXACT: "bg-green-100 text-green-800",
    FUZZY: "bg-yellow-100 text-yellow-800",
    MANUAL: "bg-blue-100 text-blue-800",
    UNMATCHED: "bg-red-100 text-red-800",
  };
  return (
    <span
      className={`inline-flex rounded-full px-2 py-0.5 text-xs font-medium ${map[level]}`}
    >
      {level}
    </span>
  );
}

function ImpactCell({
  level,
}: {
  level: "high" | "medium" | "low";
}) {
  const cfg = {
    high: { dot: "bg-red-500", label: "High" },
    medium: { dot: "bg-amber-500", label: "Mid" },
    low: { dot: "bg-gray-400", label: "Low" },
  }[level];
  return (
    <span className="inline-flex items-center gap-1.5 text-sm text-gray-700">
      <span className={`h-2 w-2 shrink-0 rounded-full ${cfg.dot}`} />
      {cfg.label}
    </span>
  );
}

function ImpactSupplierPill({ level }: { level: "high" | "medium" | "low" }) {
  const cls = {
    high: "bg-red-100 text-red-800",
    medium: "bg-amber-100 text-amber-800",
    low: "bg-gray-200 text-gray-600",
  }[level];
  const label = level === "high" ? "High" : level === "medium" ? "Medium" : "Low";
  return (
    <span
      className={`inline-flex rounded-full px-2 py-0.5 text-xs font-medium ${cls}`}
    >
      {label}
    </span>
  );
}

function PaginationFooter({
  page,
  totalPages,
  total,
  limit,
  onPrev,
  onNext,
  disabled,
}: {
  page: number;
  totalPages: number;
  total: number;
  limit: number;
  onPrev: () => void;
  onNext: () => void;
  disabled?: boolean;
}) {
  const from = total === 0 ? 0 : (page - 1) * limit + 1;
  const to = Math.min(page * limit, total);
  return (
    <div className="mt-3 flex flex-wrap items-center justify-between gap-2">
      <p className="text-sm text-gray-500">
        Showing {from}–{to} of {total} records
      </p>
      <div className="flex gap-2">
        <button
          type="button"
          disabled={disabled || page <= 1}
          onClick={onPrev}
          className="min-h-[44px] rounded border border-gray-300 bg-white px-3 py-1 text-sm text-gray-700 disabled:opacity-40"
        >
          Previous
        </button>
        <button
          type="button"
          disabled={disabled || page >= totalPages}
          onClick={onNext}
          className="min-h-[44px] rounded border border-gray-300 bg-white px-3 py-1 text-sm text-gray-700 disabled:opacity-40"
        >
          Next
        </button>
      </div>
    </div>
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
    <div className="rounded border border-red-200 bg-red-50 p-4 text-sm text-red-800">
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
  const runId = typeof params.run_id === "string" ? params.run_id : "";

  const tokenState = useAccessToken();
  const authToken =
    typeof tokenState === "string" && tokenState.length > 0
      ? tokenState
      : null;

  useEffect(() => {
    console.log(
      "results page token:",
      authToken ? authToken.slice(0, 20) : "NULL"
    );
  }, [authToken]);

  const [riskPage, setRiskPage] = useState(1);
  const [matchedPage, setMatchedPage] = useState(1);
  const [rule37Page, setRule37Page] = useState(1);
  const [section17Page, setSection17Page] = useState(1);

  const [rule37Open, setRule37Open] = useState(false);
  const [section17Open, setSection17Open] = useState(false);

  const [selectedIds, setSelectedIds] = useState<{
    itc: Set<string>;
    risk: Set<string>;
  }>(() => ({ itc: new Set(), risk: new Set() }));

  const [activeRecord, setActiveRecord] = useState<ReconcileRow | null>(null);
  const [newNoteText, setNewNoteText] = useState("");
  const [notePosting, setNotePosting] = useState(false);
  const [notePostError, setNotePostError] = useState<string | null>(null);

  const [matchedSearch, setMatchedSearch] = useState("");
  const [debouncedMatchedSearch, setDebouncedMatchedSearch] = useState("");
  useEffect(() => {
    const h = window.setTimeout(() => setDebouncedMatchedSearch(matchedSearch), 400);
    return () => window.clearTimeout(h);
  }, [matchedSearch]);

  const [matchedFilters, setMatchedFilters] = useState({
    match_level: "",
    has_notes: false,
    review_required: false,
    section_17_5: false,
    amount_min: "",
    amount_max: "",
  });

  useEffect(() => {
    setMatchedPage(1);
  }, [debouncedMatchedSearch, matchedFilters]);

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
  }, [debouncedItcFilters, itcSort]);

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
  }, [debouncedRiskFilters, riskSort]);

  const [localDecisionStatus, setLocalDecisionStatus] = useState<
    Map<string, DecisionStatus>
  >(() => new Map());

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

  const downloadPdfReport = useCallback(async () => {
    if (!authToken || !runId) return;
    setPdfDownloading(true);
    try {
      const res = await fetch(
        `${API_URL}/api/reconcile/runs/${runId}/export/pdf`,
        { headers: { Authorization: `Bearer ${authToken}` } }
      );
      if (!res.ok) throw new Error("failed");
      const blob = await res.blob();
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = "ReconDesk-report.pdf";
      document.body.appendChild(a);
      a.click();
      a.remove();
      URL.revokeObjectURL(url);
    } catch {
      addToast("Failed to generate PDF report", "error");
    } finally {
      setPdfDownloading(false);
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

  useEffect(() => {
    if (finalizeModalOpen) {
      setChecklist({ ...EMPTY_FINALIZE_CHECKLIST });
    }
  }, [finalizeModalOpen]);

  const summaryRef = useRef<HTMLDivElement>(null);
  const [summaryBarHeight, setSummaryBarHeight] = useState(0);
  useLayoutEffect(() => {
    const el = summaryRef.current;
    if (!el) return;
    const ro = new ResizeObserver(() => setSummaryBarHeight(el.offsetHeight));
    ro.observe(el);
    setSummaryBarHeight(el.offsetHeight);
    return () => ro.disconnect();
  }, []);

  const authReady = Boolean(authToken);

  const summaryKey = useMemo(
    () =>
      authReady && runId
        ? ([`/api/reconcile/runs/${runId}/summary`, authToken] as const)
        : null,
    [authReady, runId, authToken]
  );

  const {
    data: summary,
    error: summaryError,
    isLoading: summaryLoading,
    mutate: mutateSummary,
  } = useSWR<RunSummary>(summaryKey, authJsonFetcher, {
    revalidateOnFocus: false,
    isPaused: () => !authToken || !runId,
  });

  const isRunFinalized = Boolean(
    summary &&
      (summary.status === "final" || summary.status === "FINAL")
  );

  const itcListQuery = useMemo(
    () => buildItcListQueryString(itcPage, itcSort, debouncedItcFilters),
    [itcPage, itcSort, debouncedItcFilters]
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
    isPaused: () => !authToken || !runId,
  });

  const riskListQuery = useMemo(
    () => buildRiskListQueryString(riskPage, riskSort, debouncedRiskFilters),
    [riskPage, riskSort, debouncedRiskFilters]
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
    isPaused: () => !authToken || !runId,
  });

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
    {
      revalidateOnFocus: false,
      isPaused: () =>
        !authToken ||
        !runId ||
        !(
          typeof summary?.late_match_count === "number" &&
          summary.late_match_count > 0
        ),
    }
  );

  const matchedQuery = useMemo(
    () =>
      buildMatchedQuery(matchedPage, debouncedMatchedSearch, matchedFilters),
    [matchedPage, debouncedMatchedSearch, matchedFilters]
  );

  const matchedKey = useMemo(
    () =>
      authReady && runId
        ? ([`/api/reconcile/runs/${runId}/matched?${matchedQuery}`, authToken] as const)
        : null,
    [authReady, runId, matchedQuery, authToken]
  );

  const {
    data: matchedData,
    error: matchedError,
    isLoading: matchedLoading,
    mutate: mutateMatched,
  } = useSWR<Paginated<ReconcileRow>>(matchedKey, authJsonFetcher, {
    revalidateOnFocus: false,
    isPaused: () => !authToken || !runId,
  });

  const rule37ListKey = useMemo(
    () =>
      authReady && runId
        ? ([
            `/api/reconcile/runs/${runId}/rule37?page=${rule37Page}&limit=50`,
            authToken,
          ] as const)
        : null,
    [authReady, runId, rule37Page, authToken]
  );

  const {
    data: rule37Data,
    error: rule37Error,
    isLoading: rule37Loading,
    mutate: mutateRule37,
  } = useSWR<Paginated<ReconcileRow>>(rule37ListKey, authJsonFetcher, {
    revalidateOnFocus: false,
    isPaused: () => !authToken || !runId || !rule37Open,
  });

  const section17ListKey = useMemo(
    () =>
      authReady && runId
        ? ([
            `/api/reconcile/runs/${runId}/section17?page=${section17Page}&limit=50`,
            authToken,
          ] as const)
        : null,
    [authReady, runId, section17Page, authToken]
  );

  const {
    data: section17Data,
    error: section17Error,
    isLoading: section17Loading,
    mutate: mutateSection17,
  } = useSWR<Paginated<ReconcileRow>>(section17ListKey, authJsonFetcher, {
    revalidateOnFocus: false,
    isPaused: () => !authToken || !runId || !section17Open,
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
    isPaused: () => !authToken || !activeRecord,
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
    [addToast, authToken, mutateItc, mutateRisk]
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

  const finalizeBarVisible =
    summary?.user_role === "admin" && !isRunFinalized;
  const staffFinalizeMessageVisible =
    summary?.user_role === "staff" && !isRunFinalized;

  const closeFinalizeModal = useCallback(() => {
    if (finalizing) return;
    setFinalizeModalOpen(false);
    setChecklist({ ...EMPTY_FINALIZE_CHECKLIST });
  }, [finalizing]);

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

  return (
    <div
      className="min-h-screen bg-gray-50 pb-28"
      style={{ paddingTop: summaryBarHeight ? summaryBarHeight + 16 : 96 }}
    >
      {/* Sticky summary */}
      <div
        ref={summaryRef}
        className="fixed left-0 right-0 top-0 z-50 border-b border-gray-200 bg-white px-4 py-3 shadow-sm"
      >
        {summaryLoading && <SummarySkeleton />}
        {summaryError && (
          <SectionError
            message="Failed to load summary."
            onRetry={() => void mutateSummary()}
          />
        )}
        {summary && !summaryError && (
          <div className="flex flex-wrap items-start justify-between gap-4">
            <div>
              <p className="text-lg font-semibold text-gray-900">
                {summary.client_name}
              </p>
              <p className="text-sm text-gray-500">{summary.period}</p>
              <p className="text-xs text-gray-400">
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
                  <span className="mt-2 inline-flex rounded-full bg-emerald-100 px-2 py-0.5 text-xs font-medium text-emerald-800">
                    Finalized by {summary.finalized_by_name} on{" "}
                    {formatDate(summary.finalized_at)}
                  </span>
                )}
            </div>
            <div className="flex w-full flex-col gap-3 sm:flex-row sm:flex-wrap sm:items-start sm:justify-end">
              <div className="flex flex-wrap gap-4">
                <div>
                  <p className="text-sm text-gray-700">Total GSTR Records</p>
                  <p className="text-lg font-semibold text-gray-900">
                    {summary.total_gstr_records.toLocaleString("en-IN")}
                  </p>
                </div>
                <div>
                  <p className="text-sm text-gray-700">Matched</p>
                  <p className="text-lg font-semibold text-gray-900">
                    {summary.matched_count.toLocaleString("en-IN")}
                  </p>
                </div>
                <div>
                  <p className="text-2xl font-bold text-emerald-600">
                    {formatINR(summary.missed_itc_total_amount)}
                  </p>
                  <p className="text-xs text-gray-400">Missed ITC</p>
                </div>
                <div>
                  <p className="text-2xl font-bold text-red-600">
                    {formatINR(summary.wrongful_risk_total_amount)}
                  </p>
                  <p className="text-xs text-gray-400">At Risk</p>
                </div>
              </div>
              <div className="flex w-full flex-col gap-2 sm:w-auto sm:flex-row sm:items-center sm:gap-2">
                <button
                  type="button"
                  disabled={excelDownloading}
                  className="inline-flex min-h-[44px] items-center justify-center gap-1.5 rounded border border-emerald-600 px-2 py-1.5 text-xs font-medium text-emerald-600 hover:bg-emerald-50 disabled:cursor-not-allowed disabled:opacity-50"
                  onClick={() => void downloadExcelReport()}
                >
                  {excelDownloading ? (
                    <Loader2 className="h-3.5 w-3.5 shrink-0 animate-spin" />
                  ) : (
                    <FileSpreadsheet className="h-3.5 w-3.5 shrink-0" />
                  )}
                  Excel
                </button>
                <button
                  type="button"
                  disabled={pdfDownloading}
                  className="inline-flex min-h-[44px] items-center justify-center gap-1.5 rounded border border-red-600 px-2 py-1.5 text-xs font-medium text-red-600 hover:bg-red-50 disabled:cursor-not-allowed disabled:opacity-50"
                  onClick={() => void downloadPdfReport()}
                >
                  {pdfDownloading ? (
                    <Loader2 className="h-3.5 w-3.5 shrink-0 animate-spin" />
                  ) : (
                    <FileText className="h-3.5 w-3.5 shrink-0" />
                  )}
                  PDF
                </button>
              </div>
            </div>
          </div>
        )}
        {summary && !summaryError && (
          <div className="mt-3">
            <div className="h-1 w-full rounded-full bg-gray-200">
              <div
                className="h-1 rounded-full bg-emerald-500 transition-all"
                style={{
                  width: `${Math.min(100, Math.max(0, summary.match_rate_percent))}%`,
                }}
              />
            </div>
            <p className="mt-1 text-right text-xs text-gray-400">
              {summary.match_rate_percent}% matched
            </p>
          </div>
        )}
      </div>

      <div className="mx-auto max-w-7xl space-y-6 px-4">
        {/* ITC */}
        {summary &&
          summary.missed_itc_count === 0 &&
          summary.wrongful_risk_count === 0 && (
          <div className="mb-6 rounded-lg border-l-4 border-emerald-500 bg-emerald-50 p-4">
            <div className="flex gap-3">
              <Check className="mt-0.5 h-6 w-6 shrink-0 text-emerald-600" />
              <div>
                <h2 className="font-semibold text-emerald-800">Perfect match!</h2>
                <p className="mt-1 text-sm text-emerald-700">
                  No ITC missed this month. Every invoice in GSTR-2B is recorded in
                  your purchase register.
                </p>
              </div>
            </div>
          </div>
        )}

        {summary && summary.missed_itc_count > 0 && (
          <div className="mb-6 rounded-lg border-l-4 border-emerald-500 bg-emerald-50 p-4">
            <div className="mb-3 flex flex-wrap items-center justify-between gap-2">
              <h2 className="font-semibold text-emerald-800">
                ITC You Can Still Claim
              </h2>
              <div className="flex flex-wrap items-center gap-3">
                <span className="text-2xl font-bold text-emerald-700">
                  Total: {formatINR(summary.missed_itc_total_amount)}
                </span>
                <button
                  type="button"
                  disabled={itcCsvDownloading}
                  className="inline-flex min-h-[44px] items-center gap-1.5 rounded border border-emerald-700 px-2 py-1 text-xs font-medium text-emerald-800 hover:bg-emerald-100 disabled:opacity-60"
                  onClick={() => void downloadItcCsv()}
                >
                  {itcCsvDownloading ? (
                    <Loader2 className="h-3.5 w-3.5 shrink-0 animate-spin" />
                  ) : null}
                  Download CSV
                </button>
              </div>
            </div>

            <div className="mb-3 flex flex-col gap-3 lg:flex-row lg:flex-wrap lg:items-end lg:justify-between">
              <div className="flex w-full flex-col flex-wrap gap-2 sm:flex-row sm:items-center">
                <input
                  type="text"
                  inputMode="decimal"
                  className="w-full min-w-[6rem] rounded border border-emerald-600/30 bg-white px-2 py-1.5 text-sm sm:w-28"
                  placeholder="₹ Min"
                  value={itcFilters.amount_min}
                  onChange={(e) =>
                    setItcFilters((f) => ({ ...f, amount_min: e.target.value }))
                  }
                />
                <input
                  type="text"
                  inputMode="decimal"
                  className="w-full min-w-[6rem] rounded border border-emerald-600/30 bg-white px-2 py-1.5 text-sm sm:w-28"
                  placeholder="₹ Max"
                  value={itcFilters.amount_max}
                  onChange={(e) =>
                    setItcFilters((f) => ({ ...f, amount_max: e.target.value }))
                  }
                />
                <input
                  type="text"
                  className="w-full min-w-[10rem] rounded border border-emerald-600/30 bg-white px-2 py-1.5 text-sm sm:min-w-[12rem]"
                  placeholder="Filter by GSTIN..."
                  value={itcFilters.supplier_gstin}
                  onChange={(e) =>
                    setItcFilters((f) => ({
                      ...f,
                      supplier_gstin: e.target.value,
                    }))
                  }
                />
                <input
                  type="date"
                  className="w-full rounded border border-emerald-600/30 bg-white px-2 py-1.5 text-sm sm:w-auto"
                  value={itcFilters.date_from}
                  onChange={(e) =>
                    setItcFilters((f) => ({ ...f, date_from: e.target.value }))
                  }
                />
                <input
                  type="date"
                  className="w-full rounded border border-emerald-600/30 bg-white px-2 py-1.5 text-sm sm:w-auto"
                  value={itcFilters.date_to}
                  onChange={(e) =>
                    setItcFilters((f) => ({ ...f, date_to: e.target.value }))
                  }
                />
                {hasActiveItcFilters(itcFilters) && (
                  <button
                    type="button"
                    className="min-h-[44px] text-sm font-medium text-emerald-800 underline"
                    onClick={() =>
                      setItcFilters({
                        amount_min: "",
                        amount_max: "",
                        supplier_gstin: "",
                        date_from: "",
                        date_to: "",
                      })
                    }
                  >
                    Clear filters
                  </button>
                )}
              </div>
              <select
                className="min-h-[44px] w-full rounded border border-emerald-600/40 bg-white px-2 py-1.5 text-sm text-emerald-900 lg:w-auto lg:min-w-[12rem]"
                value={itcSort}
                onChange={(e) => setItcSort(e.target.value)}
              >
                <option value="amount_desc">ITC Amount ↓</option>
                <option value="amount_asc">ITC Amount ↑</option>
                <option value="supplier_name">Supplier Name</option>
                <option value="invoice_date">Invoice Date</option>
              </select>
            </div>

            {itcError && (
              <SectionError
                message="Failed to load."
                onRetry={() => void mutateItc()}
              />
            )}
            {itcLoading && !itcPageData && !itcError && (
              <div className="overflow-x-auto rounded border border-emerald-200 bg-white">
                <table className="min-w-full text-left text-sm">
                  <thead className="border-b bg-emerald-50/50">
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
                  <div className="mb-2 flex flex-wrap items-center gap-3 rounded border border-emerald-200 bg-white px-3 py-2 text-sm">
                    <span>{selectedIds.itc.size} selected</span>
                    <button
                      type="button"
                      disabled={isRunFinalized}
                      className="min-h-[44px] rounded border border-emerald-600 px-2 py-1 text-emerald-800 disabled:cursor-not-allowed disabled:opacity-50"
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
                      className="min-h-[44px] rounded border border-gray-400 px-2 py-1 text-gray-700 disabled:cursor-not-allowed disabled:opacity-50"
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
                      className="min-h-[44px] text-emerald-700 underline"
                      onClick={() =>
                        setSelectedIds((p) => ({ ...p, itc: new Set() }))
                      }
                    >
                      Clear
                    </button>
                  </div>
                )}
                <div className="overflow-x-auto rounded border border-emerald-200 bg-white">
                  <table className="min-w-full text-left text-sm">
                    <thead className="border-b bg-emerald-50/50">
                      <tr>
                        <th className="sticky left-0 z-10 bg-emerald-50/50 px-2 py-2">
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
                        <th className="px-2 py-2">#</th>
                        <th className="px-2 py-2">Supplier GSTIN</th>
                        <th className="px-2 py-2">Invoice#</th>
                        <th className="px-2 py-2">Date</th>
                        <th className="px-2 py-2 text-right">Amount</th>
                        <th className="px-2 py-2">Impact</th>
                        <th className="px-2 py-2">WHAT</th>
                        <th className="px-2 py-2">WHY</th>
                        <th className="px-2 py-2">NEXT</th>
                        <th className="px-2 py-2">Status</th>
                      </tr>
                    </thead>
                    <tbody>
                      {itcRows.map((row, i) => (
                        <tr key={row.id} className="border-b border-gray-100">
                          <td className="sticky left-0 z-10 bg-emerald-50 px-2 py-2">
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
                          <td className="px-2 py-2 text-gray-500">
                            {(itcPage - 1) * 50 + i + 1}
                          </td>
                          <td className="font-mono text-xs">{row.supplier_gstin}</td>
                          <td>{row.invoice_number}</td>
                          <td>{formatDate(row.invoice_date)}</td>
                          <td className="text-right font-mono">
                            {formatINR(row.amount)}
                          </td>
                          <td>
                            <ImpactCell
                              level={getImpactLevel(row.amount, itcMax)}
                            />
                          </td>
                          <td className="max-w-[140px] truncate text-sm font-medium text-emerald-700">
                            {row.decision_what ?? "—"}
                          </td>
                          <td className="max-w-[140px] truncate text-sm text-gray-600">
                            {row.decision_why ?? "—"}
                          </td>
                          <td className="max-w-[140px] truncate text-sm font-medium text-blue-700">
                            {row.decision_next ?? "—"}
                          </td>
                          <td>
                            <DecisionStatusPill status={effectiveStatus(row)} />
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
                <PaginationFooter
                  page={itcPageData.page}
                  totalPages={itcPageData.total_pages}
                  total={itcPageData.total}
                  limit={itcPageData.limit}
                  onPrev={() => setItcPage((p) => Math.max(1, p - 1))}
                  onNext={() =>
                    setItcPage((p) =>
                      Math.min(itcPageData.total_pages, p + 1)
                    )
                  }
                />
                <p className="mt-2 text-right text-sm font-medium text-emerald-700">
                  {formatINR(summary.missed_itc_total_amount)} ITC recoverable across{" "}
                  {itcPageData.total.toLocaleString("en-IN")} invoices
                </p>
              </>
            )}
          </div>
        )}

        {/* Risk */}
        {summary &&
          summary.wrongful_risk_count === 0 &&
          summary.missed_itc_count > 0 && (
          <div className="mb-6 rounded-lg border-l-4 border-red-500 bg-red-50 p-4">
            <div className="flex gap-3">
              <Shield className="mt-0.5 h-6 w-6 shrink-0 text-red-600" />
              <p className="text-red-800">
                No compliance risk detected for this period.
              </p>
            </div>
          </div>
        )}

        {summary && summary.wrongful_risk_count > 0 && (
          <div className="mb-6 rounded-lg border-l-4 border-red-500 bg-red-50 p-4">
            <div className="mb-3 flex flex-wrap items-center justify-between gap-2">
              <h2 className="font-semibold text-red-800">
                ITC at Risk — Supplier Has Not Filed
              </h2>
              <div className="flex flex-wrap items-center gap-3">
                <span className="text-2xl font-bold text-red-700">
                  Total: {formatINR(summary.wrongful_risk_total_amount)}
                </span>
                <button
                  type="button"
                  disabled={riskCsvDownloading}
                  className="inline-flex min-h-[44px] items-center gap-1.5 rounded border border-red-700 px-2 py-1 text-xs font-medium text-red-800 hover:bg-red-100 disabled:opacity-60"
                  onClick={() => void downloadRiskCsv()}
                >
                  {riskCsvDownloading ? (
                    <Loader2 className="h-3.5 w-3.5 shrink-0 animate-spin" />
                  ) : null}
                  Download CSV
                </button>
              </div>
            </div>

            <div className="mb-3 flex flex-col gap-3 lg:flex-row lg:flex-wrap lg:items-end lg:justify-between">
              <div className="flex w-full flex-col flex-wrap gap-2 sm:flex-row sm:items-center">
                <input
                  type="text"
                  inputMode="decimal"
                  className="w-full min-w-[6rem] rounded border border-red-600/30 bg-white px-2 py-1.5 text-sm sm:w-28"
                  placeholder="₹ Min"
                  value={riskFilters.amount_min}
                  onChange={(e) =>
                    setRiskFilters((f) => ({ ...f, amount_min: e.target.value }))
                  }
                />
                <input
                  type="text"
                  inputMode="decimal"
                  className="w-full min-w-[6rem] rounded border border-red-600/30 bg-white px-2 py-1.5 text-sm sm:w-28"
                  placeholder="₹ Max"
                  value={riskFilters.amount_max}
                  onChange={(e) =>
                    setRiskFilters((f) => ({ ...f, amount_max: e.target.value }))
                  }
                />
                <input
                  type="text"
                  className="w-full min-w-[10rem] rounded border border-red-600/30 bg-white px-2 py-1.5 text-sm sm:min-w-[12rem]"
                  placeholder="Filter by GSTIN..."
                  value={riskFilters.supplier_gstin}
                  onChange={(e) =>
                    setRiskFilters((f) => ({
                      ...f,
                      supplier_gstin: e.target.value,
                    }))
                  }
                />
                <select
                  className="min-h-[44px] w-full rounded border border-red-600/30 bg-white px-2 py-1.5 text-sm sm:w-auto sm:min-w-[8rem]"
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
                {hasActiveRiskFilters(riskFilters) && (
                  <button
                    type="button"
                    className="min-h-[44px] text-sm font-medium text-red-800 underline"
                    onClick={() =>
                      setRiskFilters({
                        amount_min: "",
                        amount_max: "",
                        supplier_gstin: "",
                        risk_level: "",
                      })
                    }
                  >
                    Clear filters
                  </button>
                )}
              </div>
              <select
                className="min-h-[44px] w-full rounded border border-red-600/40 bg-white px-2 py-1.5 text-sm text-red-900 lg:w-auto lg:min-w-[12rem]"
                value={riskSort}
                onChange={(e) => setRiskSort(e.target.value)}
              >
                <option value="amount_desc">ITC at Risk ↓</option>
                <option value="amount_asc">ITC at Risk ↑</option>
                <option value="supplier_name">Supplier Name</option>
                <option value="invoice_date">Invoice Date</option>
              </select>
            </div>

            {riskError && (
              <SectionError
                message="Failed to load."
                onRetry={() => void mutateRisk()}
              />
            )}
            {riskLoading && !riskPageData && !riskError && (
              <div className="overflow-x-auto rounded border border-red-200 bg-white">
                <table className="min-w-full text-left text-sm">
                  <thead className="border-b bg-red-50/50">
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
                {selectedIds.risk.size > 0 && (
                  <div className="mb-2 flex flex-wrap items-center gap-3 rounded border border-red-200 bg-white px-3 py-2 text-sm">
                    <span>{selectedIds.risk.size} selected</span>
                    <button
                      type="button"
                      disabled={isRunFinalized}
                      className="min-h-[44px] rounded border border-red-600 px-2 py-1 text-red-800 disabled:cursor-not-allowed disabled:opacity-50"
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
                      className="min-h-[44px] rounded border border-gray-400 px-2 py-1 text-gray-700 disabled:cursor-not-allowed disabled:opacity-50"
                      onClick={() => {
                        const snap = new Set(selectedIds.risk);
                        void runBulkDecision("risk", Array.from(snap), "ignored", snap);
                      }}
                    >
                      Mark as Ignored
                    </button>
                    <button
                      type="button"
                      className="min-h-[44px] text-red-700 underline"
                      onClick={() =>
                        setSelectedIds((p) => ({ ...p, risk: new Set() }))
                      }
                    >
                      Clear
                    </button>
                  </div>
                )}
                <div className="overflow-x-auto rounded border border-red-200 bg-white">
                  <table className="min-w-full text-left text-sm">
                    <thead className="border-b bg-red-50/50">
                      <tr>
                        <th className="sticky left-0 z-10 bg-red-50/50 px-2 py-2">
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
                        <th className="px-2 py-2">#</th>
                        <th className="px-2 py-2">Supplier GSTIN</th>
                        <th className="px-2 py-2">Invoice#</th>
                        <th className="px-2 py-2">Date</th>
                        <th className="px-2 py-2 text-right">Amount</th>
                        <th className="px-2 py-2">Impact</th>
                        <th className="px-2 py-2">WHAT</th>
                        <th className="px-2 py-2">WHY</th>
                        <th className="px-2 py-2">NEXT</th>
                        <th className="px-2 py-2">Status</th>
                        <th className="px-2 py-2 text-right text-xs font-medium text-gray-600">
                          Generate Notice
                        </th>
                      </tr>
                    </thead>
                    <tbody>
                      {riskRows.map((row, i) => (
                        <tr key={row.id} className="border-b border-gray-100">
                          <td className="sticky left-0 z-10 bg-red-50 px-2 py-2">
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
                          <td className="px-2 py-2 text-gray-500">
                            {(riskPage - 1) * 50 + i + 1}
                          </td>
                          <td className="font-mono text-xs">{row.supplier_gstin}</td>
                          <td>{row.invoice_number}</td>
                          <td>{formatDate(row.invoice_date)}</td>
                          <td className="text-right font-mono">
                            {formatINR(row.amount)}
                          </td>
                          <td>
                            <ImpactCell
                              level={getImpactLevel(row.amount, riskMax)}
                            />
                          </td>
                          <td className="max-w-[140px] truncate text-sm font-medium text-red-700">
                            {row.decision_what ?? "—"}
                          </td>
                          <td className="max-w-[140px] truncate text-sm text-gray-600">
                            {row.decision_why ?? "—"}
                          </td>
                          <td className="max-w-[140px] truncate text-sm font-medium text-blue-700">
                            {row.decision_next ?? "—"}
                          </td>
                          <td>
                            <DecisionStatusPill status={effectiveStatus(row)} />
                          </td>
                          <td className="px-2 py-2 text-right">
                            <button
                              type="button"
                              disabled
                              title="Coming Soon — Phase 7"
                              className="min-h-[44px] whitespace-nowrap rounded border border-gray-300 bg-white px-2 py-1 text-xs font-medium text-gray-500 disabled:cursor-not-allowed disabled:opacity-60"
                            >
                              Generate Notice
                            </button>
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
                <PaginationFooter
                  page={riskPageData.page}
                  totalPages={riskPageData.total_pages}
                  total={riskPageData.total}
                  limit={riskPageData.limit}
                  onPrev={() => setRiskPage((p) => Math.max(1, p - 1))}
                  onNext={() =>
                    setRiskPage((p) =>
                      Math.min(riskPageData.total_pages, p + 1)
                    )
                  }
                />
                <p className="mt-2 text-right text-sm font-medium text-red-700">
                  {formatINR(summary.wrongful_risk_total_amount)} ITC at risk across{" "}
                  {riskPageData.total.toLocaleString("en-IN")} invoices
                </p>
              </>
            )}
          </div>
        )}

        {summary && summary.wrongful_risk_count > 0 && (
          <div className="mb-6 rounded-lg border border-gray-200 bg-white p-4 shadow-sm">
            <h2 className="mb-3 text-lg font-semibold text-gray-900">
              Top Suppliers by ITC at Risk
            </h2>
            {riskLoading && !riskPageData && (
              <div className="animate-pulse space-y-2 py-2">
                <div className="h-8 rounded bg-gray-100" />
                <div className="h-8 rounded bg-gray-100/90" />
                <div className="h-8 rounded bg-gray-100/80" />
              </div>
            )}
            {!(riskLoading && !riskPageData) && topSuppliersByRisk.length === 0 && (
              <p className="text-sm text-gray-500">No supplier risk data available.</p>
            )}
            {!(riskLoading && !riskPageData) && topSuppliersByRisk.length > 0 && (
              <>
                <div className="overflow-x-auto">
                  <table className="min-w-full text-left text-sm">
                    <thead className="border-b bg-gray-50">
                      <tr>
                        <th className="sticky left-0 z-10 bg-gray-50 px-3 py-2">
                          Supplier GSTIN
                        </th>
                        <th className="px-3 py-2">Trade Name</th>
                        <th className="px-3 py-2 text-right">Invoice Count</th>
                        <th className="px-3 py-2 text-right">Total ITC at Risk</th>
                        <th className="px-3 py-2">Impact</th>
                      </tr>
                    </thead>
                    <tbody>
                      {topSuppliersByRisk.map((s) => (
                        <tr key={s.gstin} className="border-b border-gray-100">
                          <td className="sticky left-0 z-10 bg-white px-3 py-2 font-mono text-xs">
                            {s.gstin}
                          </td>
                          <td className="max-w-[200px] truncate px-3 py-2 text-gray-700">
                            {s.tradeName || "—"}
                          </td>
                          <td className="px-3 py-2 text-right tabular-nums">
                            {s.count.toLocaleString("en-IN")}
                          </td>
                          <td className="px-3 py-2 text-right font-mono">
                            {formatINR(s.total)}
                          </td>
                          <td className="px-3 py-2">
                            <ImpactSupplierPill level={s.impact} />
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
                <div className="mt-3 text-right">
                  <Link
                    href="/intelligence"
                    className="text-sm font-medium text-blue-700 hover:underline"
                  >
                    View full vendor intelligence →
                  </Link>
                </div>
              </>
            )}
          </div>
        )}

        {summary &&
          typeof summary.late_match_count === "number" &&
          summary.late_match_count > 0 && (
            <div className="mb-6 rounded-lg border-l-4 border-emerald-400 bg-emerald-50 p-4">
              <p className="mb-3 font-semibold text-emerald-800">
                {summary.late_match_count.toLocaleString("en-IN")} invoices
                matched from previous periods
              </p>
              {lateMatchesLoading && (
                <div className="animate-pulse space-y-2 py-2">
                  <div className="h-6 rounded bg-emerald-100/90" />
                  <div className="h-6 rounded bg-emerald-100/70" />
                  <div className="h-6 rounded bg-emerald-100/50" />
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
                  <div className="overflow-x-auto rounded border border-emerald-200/70 bg-white">
                    <table className="min-w-full text-left text-sm">
                      <thead className="border-b bg-emerald-50/80">
                        <tr>
                          <th className="sticky left-0 z-10 bg-emerald-50/80 px-3 py-2">
                            Supplier
                          </th>
                          <th className="px-3 py-2">Invoice#</th>
                          <th className="px-3 py-2">Original Period</th>
                          <th className="px-3 py-2">GSTR-2B Period</th>
                          <th className="px-3 py-2 text-right">Months Late</th>
                        </tr>
                      </thead>
                      <tbody>
                        {(lateMatchesData?.data ?? []).map((row, idx) => (
                          <tr
                            key={`${row.supplier_gstin}-${row.invoice_number}-${idx}`}
                            className="border-b border-gray-100"
                          >
                            <td className="sticky left-0 z-10 bg-white px-3 py-2 font-mono text-xs">
                              {row.supplier_gstin || "—"}
                            </td>
                            <td className="px-3 py-2">{row.invoice_number || "—"}</td>
                            <td className="px-3 py-2">{row.original_period || "—"}</td>
                            <td className="px-3 py-2">{row.gstr2b_period || "—"}</td>
                            <td className="px-3 py-2 text-right font-medium tabular-nums text-emerald-700">
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
        <div className="mb-6 rounded-lg border border-gray-200 bg-white p-4">
          <h2 className="mb-3 text-lg font-semibold text-gray-900">
            Matched Records{" "}
            {matchedData != null && (
              <span className="font-normal text-gray-500">
                ({matchedData.total})
              </span>
            )}
          </h2>

          <div className="mb-3 space-y-2">
            <input
              type="search"
              className="w-full rounded border border-gray-300 px-3 py-2 text-sm"
              placeholder="Search by supplier GSTIN or invoice number..."
              value={matchedSearch}
              onChange={(e) => setMatchedSearch(e.target.value)}
            />
            <div className="flex flex-wrap items-center gap-2">
              <select
                className="min-h-[44px] rounded border border-gray-300 px-2 py-1 text-sm"
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
                className="w-28 rounded border border-gray-300 px-2 py-1 text-sm"
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
                className="w-28 rounded border border-gray-300 px-2 py-1 text-sm"
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
                className={`min-h-[36px] rounded-full border px-2 py-1 text-xs ${
                  matchedFilters.has_notes
                    ? "border-blue-600 bg-blue-50 text-blue-800"
                    : "border-gray-300 text-gray-600"
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
                className={`min-h-[36px] rounded-full border px-2 py-1 text-xs ${
                  matchedFilters.review_required
                    ? "border-amber-600 bg-amber-50 text-amber-800"
                    : "border-gray-300 text-gray-600"
                }`}
                onClick={() =>
                  setMatchedFilters((f) => ({
                    ...f,
                    review_required: !f.review_required,
                  }))
                }
              >
                Review Required
              </button>
              <button
                type="button"
                className={`min-h-[36px] rounded-full border px-2 py-1 text-xs ${
                  matchedFilters.section_17_5
                    ? "border-gray-700 bg-gray-100 text-gray-800"
                    : "border-gray-300 text-gray-600"
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
              {hasActiveMatchedFilters(debouncedMatchedSearch, matchedFilters) && (
                <button
                  type="button"
                  className="min-h-[44px] text-sm text-blue-600 underline"
                  onClick={() => {
                    setMatchedSearch("");
                    setDebouncedMatchedSearch("");
                    setMatchedFilters({
                      match_level: "",
                      has_notes: false,
                      review_required: false,
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
          </div>

          {matchedError && (
            <SectionError
              message="Failed to load."
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
              <div className="rounded border border-gray-100 bg-gray-50 p-6 text-center">
                <p className="text-gray-600">
                  No records match your filters. Try adjusting the search or
                  filters.
                </p>
                <button
                  type="button"
                  className="mt-3 min-h-[44px] rounded bg-gray-200 px-3 py-1 text-sm text-gray-800"
                  onClick={() => {
                    setMatchedSearch("");
                    setDebouncedMatchedSearch("");
                    setMatchedFilters({
                      match_level: "",
                      has_notes: false,
                      review_required: false,
                      section_17_5: false,
                      amount_min: "",
                      amount_max: "",
                    });
                    setMatchedPage(1);
                  }}
                >
                  Clear filters
                </button>
              </div>
            )}
          {matchedData && !matchedError && matchedData.data.length > 0 && (
            <>
              <div className="overflow-x-auto">
                <table className="min-w-full text-left text-sm">
                  <thead className="border-b bg-gray-50">
                    <tr>
                      <th className="sticky left-0 z-10 bg-gray-50 px-2 py-2">
                        Supplier
                      </th>
                      <th className="px-2 py-2">Invoice#</th>
                      <th className="px-2 py-2">Date</th>
                      <th className="px-2 py-2 text-right">Amount</th>
                      <th className="px-2 py-2">Match Level</th>
                      <th className="px-2 py-2">Confidence</th>
                      <th className="px-2 py-2">Discrepancy</th>
                      <th className="px-2 py-2">Notes</th>
                    </tr>
                  </thead>
                  <tbody>
                    {matchedData.data.map((row) => (
                      <tr
                        key={row.id}
                        className="group cursor-pointer border-b border-gray-100 hover:bg-gray-50"
                        onClick={() => {
                          setActiveRecord(row);
                          setDrawerDecisionError(null);
                          setNotePostError(null);
                        }}
                      >
                        <td className="sticky left-0 z-10 bg-white px-2 py-2 font-mono text-xs group-hover:bg-gray-50">
                          {row.supplier_gstin}
                        </td>
                        <td>{row.invoice_number}</td>
                        <td>{formatDate(row.invoice_date)}</td>
                        <td className="text-right font-mono">
                          {formatINR(row.amount)}
                        </td>
                        <td>
                          <MatchLevelBadge level={row.match_level} />
                        </td>
                        <td>
                          {Math.round(
                            Math.min(1, Math.max(0, row.confidence_score)) *
                              100
                          )}
                          %
                        </td>
                        <td className="max-w-[180px] truncate text-gray-700">
                          {row.discrepancy_note ?? "—"}
                        </td>
                        <td>
                          {row.notes_count > 0 ? (
                            <span className="inline-flex rounded-full bg-gray-100 px-2 py-0.5 text-xs text-gray-600">
                              {row.notes_count} notes
                            </span>
                          ) : (
                            "—"
                          )}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
              <PaginationFooter
                page={matchedData.page}
                totalPages={matchedData.total_pages}
                total={matchedData.total}
                limit={matchedData.limit}
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

        {/* Rule 37 */}
        <div className="mb-6 rounded-lg border border-gray-200 bg-white">
          <button
            type="button"
            className="flex min-h-[44px] w-full items-center justify-between px-4 py-3 text-left hover:bg-gray-50"
            onClick={() => setRule37Open((o) => !o)}
          >
            <span className="flex items-center gap-2 font-semibold text-gray-900">
              Rule 37 — 180 Day Payment Warnings
              {rule37Data != null && (
                <span className="rounded-full bg-gray-100 px-2 py-0.5 text-xs font-normal text-gray-700">
                  {rule37Data.total}
                </span>
              )}
            </span>
            <ChevronDown
              className={`h-5 w-5 shrink-0 text-gray-500 transition-transform ${
                rule37Open ? "rotate-180" : ""
              }`}
            />
          </button>
          {rule37Open && (
            <div className="border-t border-gray-100 px-4 py-3">
              {rule37Error && (
                <SectionError
                  message="Failed to load."
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
                  const border =
                    u === "CRITICAL"
                      ? "border-l-4 border-red-500 bg-red-50"
                      : u === "HIGH"
                        ? "border-l-4 border-orange-400 bg-orange-50"
                        : "border-l-4 border-yellow-400 bg-yellow-50";
                  const badge =
                    u === "CRITICAL"
                      ? "bg-red-100 text-red-800"
                      : u === "HIGH"
                        ? "bg-orange-100 text-orange-800"
                        : "bg-yellow-100 text-yellow-800";
                  return (
                    <div
                      key={row.id}
                      className={`relative mb-2 rounded-r-lg border border-gray-100 p-3 pl-4 ${border}`}
                    >
                      <span
                        className={`absolute right-2 top-2 rounded-full px-2 py-0.5 text-xs font-medium ${badge}`}
                      >
                        {u}
                      </span>
                      <div className="flex flex-wrap gap-2 pr-24 text-sm">
                        <span className="font-mono text-xs">{row.supplier_gstin}</span>
                        <span>{row.invoice_number}</span>
                        <span>{formatDate(row.invoice_date)}</span>
                        <span className="font-mono">{formatINR(row.amount)}</span>
                      </div>
                      <div className="mt-2 grid gap-1 text-sm sm:grid-cols-3">
                        <span className="font-medium text-emerald-800">
                          {row.decision_what ?? "—"}
                        </span>
                        <span className="text-gray-600">
                          {row.decision_why ?? "—"}
                        </span>
                        <span className="font-medium text-blue-700">
                          {row.decision_next ?? "—"}
                        </span>
                      </div>
                    </div>
                  );
                })}
              {rule37Data &&
                !rule37Error &&
                rule37Data.total_pages > 1 && (
                  <PaginationFooter
                    page={rule37Data.page}
                    totalPages={rule37Data.total_pages}
                    total={rule37Data.total}
                    limit={rule37Data.limit}
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

        {/* Section 17(5) */}
        <div className="mb-6 rounded-lg border border-gray-200 bg-white">
          <button
            type="button"
            className="flex min-h-[44px] w-full items-center justify-between px-4 py-3 text-left hover:bg-gray-50"
            onClick={() => setSection17Open((o) => !o)}
          >
            <span className="flex items-center gap-2 font-semibold text-gray-900">
              Section 17(5) — Blocked ITC Flags
              {section17Data != null && (
                <span className="rounded-full bg-gray-100 px-2 py-0.5 text-xs font-normal text-gray-700">
                  {section17Data.total}
                </span>
              )}
            </span>
            <ChevronDown
              className={`h-5 w-5 shrink-0 text-gray-500 transition-transform ${
                section17Open ? "rotate-180" : ""
              }`}
            />
          </button>
          {section17Open && (
            <div className="border-t border-gray-100 px-4 py-3">
              {section17Error && (
                <SectionError
                  message="Failed to load."
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
                    className="mb-2 rounded border border-gray-100 bg-gray-50/50 p-3"
                  >
                    {row.section_17_5_category && (
                      <span className="mb-2 inline-block rounded-full bg-gray-100 px-2 py-0.5 text-xs text-gray-700">
                        {row.section_17_5_category}
                      </span>
                    )}
                    <div className="grid gap-1 text-sm sm:grid-cols-3">
                      <span className="font-medium text-emerald-800">
                        {row.decision_what ?? "—"}
                      </span>
                      <span className="text-gray-600">
                        {row.decision_why ?? "—"}
                      </span>
                      <span className="font-medium text-blue-700">
                        {row.decision_next ?? "—"}
                      </span>
                    </div>
                  </div>
                ))}
              {section17Data &&
                !section17Error &&
                section17Data.total_pages > 1 && (
                  <PaginationFooter
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
          <aside className="fixed bottom-0 right-0 top-0 z-50 flex h-full w-full flex-col border-l border-gray-200 bg-white shadow-xl sm:w-[640px]">
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
                  const left = readDataField(activeRecord.gstr2b_data, keys);
                  const right = readDataField(
                    activeRecord.purchase_register_data,
                    keys
                  );
                  const mismatch =
                    !normCompare(left, right) &&
                    !(left === "—" && right === "—");
                  return (
                    <div key={label} className="contents">
                      <div className={mismatch ? "rounded bg-amber-50 p-2" : ""}>
                        <p className="text-xs text-gray-400">{label}</p>
                        <p
                          className={`text-sm ${
                            mismatch
                              ? "font-medium text-amber-800"
                              : "text-gray-800"
                          }`}
                        >
                          {left}
                        </p>
                      </div>
                      <div className={mismatch ? "rounded bg-amber-50 p-2" : ""}>
                        <p className="text-xs text-gray-400">{label}</p>
                        <p
                          className={`text-sm ${
                            mismatch
                              ? "font-medium text-amber-800"
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

              <div className="rounded-lg border border-teal-200 bg-teal-50 p-4">
                <p className="mb-2 text-sm font-semibold text-teal-700">
                  Decision
                </p>
                <p className="text-xs font-semibold uppercase tracking-wide text-teal-600">
                  WHAT IS WRONG
                </p>
                <p className="mb-3 text-sm text-gray-800">
                  {activeRecord.decision_what ?? "—"}
                </p>
                <p className="text-xs font-semibold uppercase tracking-wide text-teal-600">
                  WHY
                </p>
                <p className="mb-3 text-sm text-gray-800">
                  {activeRecord.decision_why ?? "—"}
                </p>
                <p className="text-xs font-semibold uppercase tracking-wide text-teal-600">
                  WHAT TO DO NEXT
                </p>
                <p className="mb-3 text-sm text-gray-800">
                  {activeRecord.decision_next ?? "—"}
                </p>
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
                    className="min-h-[44px] rounded border border-emerald-600 px-3 py-1 text-sm text-emerald-800 disabled:cursor-not-allowed disabled:opacity-50"
                    onClick={() =>
                      void runSingleDecision(activeRecord.id, "acted")
                    }
                  >
                    Mark as Acted
                  </button>
                  <button
                    type="button"
                    disabled={isRunFinalized}
                    className="min-h-[44px] rounded border border-gray-400 px-3 py-1 text-sm text-gray-700 disabled:cursor-not-allowed disabled:opacity-50"
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
        <div className="fixed bottom-0 left-0 right-0 z-40 border-t border-gray-200 bg-white py-3 px-4 shadow-lg">
          <div className="mx-auto flex max-w-7xl flex-wrap items-center justify-between gap-3">
            <p className="text-sm text-gray-500">
              Review all sections before finalizing
            </p>
            <button
              type="button"
              className="inline-flex min-h-[44px] items-center gap-2 rounded-lg bg-emerald-600 px-6 py-2 text-white hover:bg-emerald-700"
              onClick={() => setFinalizeModalOpen(true)}
            >
              Finalize Reconciliation
            </button>
          </div>
        </div>
      )}

      {staffFinalizeMessageVisible && (
        <div className="fixed bottom-0 left-0 right-0 z-40 border-t border-blue-200 bg-blue-50 py-3 px-6">
          <p className="text-center text-sm text-blue-700">
            Only your CA principal (admin) can finalize this reconciliation.
          </p>
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
          <div className="relative mx-4 max-h-[90vh] w-full max-w-lg overflow-y-auto rounded-xl bg-white p-6 shadow-xl">
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
                          ? "border-emerald-500 bg-emerald-500 text-white"
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
                  <div className="mt-1 h-1.5 w-full rounded-full bg-gray-200">
                    <div
                      className="h-1.5 rounded-full bg-emerald-500 transition-all"
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
                className="min-h-[44px] rounded-lg border border-gray-300 bg-white px-4 py-2 text-sm font-medium text-gray-700 disabled:cursor-not-allowed disabled:opacity-50"
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
                className="inline-flex min-h-[44px] items-center gap-2 rounded-lg bg-emerald-600 px-6 py-2 text-sm font-medium text-white hover:bg-emerald-700 disabled:cursor-not-allowed disabled:opacity-50"
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
            className={`pointer-events-auto rounded-lg px-4 py-2 text-sm shadow-lg transition-opacity duration-300 ${
              t.type === "success" ? "bg-emerald-600 text-white" : "bg-red-600 text-white"
            }`}
          >
            {t.message}
          </div>
        ))}
      </div>
    </div>
  );
}
