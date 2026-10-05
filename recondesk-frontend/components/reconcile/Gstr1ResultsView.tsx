"use client";

import {
  AlertTriangle,
  ArrowUpDown,
  Check,
  CheckCircle,
  ChevronDown,
  ChevronUp,
  FileSpreadsheet,
  FileText,
  Layers,
  LayoutGrid,
  List,
  Loader2,
  RotateCcw,
  Search,
  Table as TableIcon,
  X,
  XCircle,
} from "lucide-react";
import Link from "next/link";
import { useEffect, useMemo, useRef, useState } from "react";

import styles from "./gstr1Results.module.css";
import {
  DecisionInvoiceCard,
  DecisionInvoiceList,
} from "@/components/reconcile/DecisionInvoiceCard";
import {
  Gstr1ReviewWorkspace,
  generateReviewScopeKey,
} from "@/components/reconcile/Gstr1ReviewWorkspace";
import { safeStorageGet } from "@/lib/safeStorage";
import { AuditObservationsPanel } from "@/components/AuditObservationsPanel";
import { Gstr1DocumentsIssuedPanel } from "@/components/reconcile/Gstr1DocumentsIssuedPanel";
import { Gstr1aWindowBadge } from "@/components/reconcile/Gstr1aWindowBadge";
import { Gstr1TieOutPanel } from "@/components/reconcile/Gstr1TieOutPanel";
import { ReconcilePaginationFooter } from "@/components/reconcile/ReconcilePaginationFooter";
import {
  EmptyTableState,
  SALES_RESULTS_BUCKET_TABS,
  type ResultsBucketTabId,
} from "@/components/reconcile/ResultsUi";
import { toFilingPeriodYyyyMm } from "@/components/filing/filingHelpers";
import { formatINR } from "@/lib/format";
import {
  countMismatchesByType,
  filterGstr1aEligibleMismatches,
  filterReviewRequired,
  mismatchTypeShort,
  recordAmountRupees,
  recordGstin,
  recordInvoiceNumber,
  type Gstr1aWindow,
  type Gstr1MatchedRow,
  type Gstr1ReconcileResult,
  type Gstr1UnmatchedRow,
} from "@/lib/gstr1Reconcile";
import {
  downloadGstr1ExcelReport,
  downloadGstr1PdfReport,
} from "@/lib/gstr1ReconcileExport";

function SeverityPill({ severity }: { severity?: string | null }) {
  const s = String(severity || "").toLowerCase();
  const tone =
    s === "critical"
      ? "bg-[#FEECEE] text-[#9C3843] border border-[#FCD3D7]"
      : s === "high" || s === "medium"
        ? "bg-[#FFF5DD] text-[#97621C] border border-[#FDE7B2]"
        : "bg-[#F0EAF7] text-[#554260] border border-[#E8E0F1]";
  return (
    <span
      className={`inline-flex items-center rounded-full px-2.5 py-0.5 text-[11px] font-semibold capitalize ${tone}`}
    >
      {severity || "—"}
    </span>
  );
}

function TypePill({ type }: { type?: string }) {
  return (
    <span className="inline-flex items-center rounded-full bg-[#F0EAF7] text-[#554260] border border-[#E5DCEE] px-2.5 py-0.5 text-[11px] font-semibold">
      {mismatchTypeShort(type)}
    </span>
  );
}

function gstinDisplay(raw: string): string {
  return raw.trim() || "Unregistered B2C";
}

function MatchedCards({
  rows,
  emptyTitle,
  emptyDescription,
}: {
  rows: Gstr1MatchedRow[];
  emptyTitle: string;
  emptyDescription?: string;
}) {
  if (rows.length === 0) {
    return (
      <EmptyTableState title={emptyTitle} description={emptyDescription} />
    );
  }
  return (
    <DecisionInvoiceList>
      {rows.map((row, i) => {
        const sr = row.sr_record || {};
        return (
          <DecisionInvoiceCard
            key={`${recordInvoiceNumber(sr)}-${i}`}
            index={i + 1}
            gstin={gstinDisplay(recordGstin(sr))}
            invoiceNumber={recordInvoiceNumber(sr)}
            invoiceDate={String(sr.invoice_date || "—")}
            amount={recordAmountRupees(sr)}
            amountCaption="Taxable"
            what={row.decision_what || row.review_reason || "Matched"}
            why={
              row.decision_why ||
              (row.discrepancies?.length
                ? row.discrepancies.join(" · ")
                : "Sales Register and GSTR-1 align within matching rules.")
            }
            next={
              row.decision_next ||
              (row.requires_human_review
                ? "Verify invoice details before filing."
                : "No action required.")
            }
            status={
              <span className="inline-flex items-center rounded-full bg-[#E7F8EE] border border-[#D1F2DD] px-2.5 py-0.5 text-[11px] font-semibold text-[#237B51]">
                L{row.match_level ?? "—"} · {row.confidence ?? "—"}%
              </span>
            }
            meta={
              row.decision_confidence ? (
                <span className="text-[11px] text-[#968BA2]">
                  {row.decision_confidence}
                </span>
              ) : null
            }
          />
        );
      })}
    </DecisionInvoiceList>
  );
}

function UnmatchedCards({
  rows,
  emptyTitle,
  gstr1aWindow,
}: {
  rows: Gstr1UnmatchedRow[];
  emptyTitle: string;
  gstr1aWindow?: Gstr1aWindow | null;
}) {
  if (rows.length === 0) {
    return <EmptyTableState title={emptyTitle} />;
  }
  return (
    <DecisionInvoiceList>
      {rows.map((row, i) => {
        const rec = row.record || {};
        return (
          <DecisionInvoiceCard
            key={`${recordInvoiceNumber(rec)}-${i}`}
            index={i + 1}
            gstin={gstinDisplay(
              recordGstin(rec) || String(row.recipient_gstin || "")
            )}
            invoiceNumber={recordInvoiceNumber(rec)}
            invoiceDate={String(rec.invoice_date || "—")}
            amount={recordAmountRupees(rec)}
            amountCaption="Taxable"
            what={row.decision_what}
            why={row.decision_why}
            next={row.decision_next}
            status={<SeverityPill severity={row.mismatch_severity} />}
            impact={<TypePill type={row.mismatch_type} />}
            meta={
              <Gstr1aWindowBadge
                eligibility={row.eligibility}
                window={gstr1aWindow}
              />
            }
          />
        );
      })}
    </DecisionInvoiceList>
  );
}

interface TableRowData {
  id: string;
  invoiceNumber: string;
  invoiceDate: string;
  customerName: string;
  gstin: string;
  taxableValue: number;
  igst: number;
  cgst: number;
  sgst: number;
  statusBadge: React.ReactNode;
}

function Gstr1InvoicesTable({
  rows,
  emptyTitle,
}: {
  rows: TableRowData[];
  emptyTitle: string;
}) {
  const [selectedIds, setSelectedIds] = useState<Set<string>>(new Set());
  const [searchQuery, setSearchQuery] = useState("");
  const [sortField, setSortField] = useState<"date" | "taxable" | "invoice">("date");
  const [sortAsc, setSortAsc] = useState(false);
  const [page, setPage] = useState(1);
  const [pageSize, setPageSize] = useState(50);

  const filtered = useMemo(() => {
    let list = rows;
    const q = searchQuery.trim().toLowerCase();
    if (q) {
      list = list.filter(
        (r) =>
          r.invoiceNumber.toLowerCase().includes(q) ||
          r.customerName.toLowerCase().includes(q) ||
          r.gstin.toLowerCase().includes(q)
      );
    }
    return list.slice().sort((a, b) => {
      let cmp = 0;
      if (sortField === "taxable") {
        cmp = a.taxableValue - b.taxableValue;
      } else if (sortField === "date") {
        cmp = (a.invoiceDate || "").localeCompare(b.invoiceDate || "");
      } else {
        cmp = a.invoiceNumber.localeCompare(b.invoiceNumber);
      }
      return sortAsc ? cmp : -cmp;
    });
  }, [rows, searchQuery, sortField, sortAsc]);

  const totalPages = Math.max(1, Math.ceil(filtered.length / pageSize));
  const currentPage = Math.min(page, totalPages);
  const paginated = useMemo(() => {
    const start = (currentPage - 1) * pageSize;
    return filtered.slice(start, start + pageSize);
  }, [filtered, currentPage, pageSize]);

  const allPageSelected =
    paginated.length > 0 && paginated.every((r) => selectedIds.has(r.id));

  const toggleSelectAllPage = () => {
    const next = new Set(selectedIds);
    if (allPageSelected) {
      for (const r of paginated) next.delete(r.id);
    } else {
      for (const r of paginated) next.add(r.id);
    }
    setSelectedIds(next);
  };

  const toggleSelect = (id: string) => {
    const next = new Set(selectedIds);
    if (next.has(id)) next.delete(id);
    else next.add(id);
    setSelectedIds(next);
  };

  const toggleSort = (field: "date" | "taxable" | "invoice") => {
    if (sortField === field) {
      setSortAsc(!sortAsc);
    } else {
      setSortField(field);
      setSortAsc(false);
    }
  };

  if (rows.length === 0) {
    return <EmptyTableState title={emptyTitle} />;
  }

  return (
    <div className="space-y-3">
      {/* Table controls */}
      <div className="flex flex-wrap items-center justify-between gap-3 px-1 py-1">
        <div className="flex flex-1 min-w-[220px] max-w-sm items-center gap-2 rounded-[8px] border border-[#E5DCEE] bg-white px-3 py-1.5 shadow-xs">
          <Search className="h-4 w-4 text-[#968BA2] shrink-0" />
          <input
            type="text"
            value={searchQuery}
            onChange={(e) => {
              setSearchQuery(e.target.value);
              setPage(1);
            }}
            placeholder="Search invoice, customer, GSTIN…"
            className="w-full bg-transparent text-xs text-[#342B40] placeholder:text-[#968BA2] outline-none"
          />
          {searchQuery && (
            <button
              type="button"
              onClick={() => setSearchQuery("")}
              className="text-[#968BA2] hover:text-[#342B40]"
            >
              <X className="h-3.5 w-3.5" />
            </button>
          )}
        </div>
        <div className="flex items-center gap-2 text-xs text-[#756184]">
          <span>
            Showing <strong>{filtered.length.toLocaleString("en-IN")}</strong> of{" "}
            {rows.length.toLocaleString("en-IN")}
          </span>
          {selectedIds.size > 0 && (
            <span className="rounded-full bg-[#F0EAF7] px-2.5 py-0.5 font-semibold text-[#554260] border border-[#E8E0F1]">
              {selectedIds.size} selected
            </span>
          )}
        </div>
      </div>

      {/* Table wrapper */}
      <div className="overflow-x-auto rounded-[12px] border border-[#E8E0F1] bg-white shadow-xs">
        <table className="w-full min-w-[900px] border-collapse text-left text-[13px]">
          <thead>
            <tr className="border-b border-[#EEE8F4] bg-[#FAF9FC] text-[11px] font-bold uppercase tracking-[0.5px] text-[#968BA2]">
              <th className="w-10 px-4 py-3">
                <input
                  type="checkbox"
                  checked={allPageSelected}
                  onChange={toggleSelectAllPage}
                  className="rounded border-[#D8CDE3] text-[#78608F] focus:ring-[#78608F]"
                  aria-label="Select all rows on current page"
                />
              </th>
              <th
                className="cursor-pointer px-4 py-3 hover:text-[#342B40]"
                onClick={() => toggleSort("invoice")}
              >
                <div className="flex items-center gap-1">
                  <span>Invoice No.</span>
                  {sortField === "invoice" && (
                    sortAsc ? <ChevronUp className="h-3 w-3" /> : <ChevronDown className="h-3 w-3" />
                  )}
                </div>
              </th>
              <th
                className="cursor-pointer px-4 py-3 hover:text-[#342B40]"
                onClick={() => toggleSort("date")}
              >
                <div className="flex items-center gap-1">
                  <span>Invoice Date</span>
                  <ArrowUpDown className="h-3 w-3 text-[#B8ADC2]" />
                </div>
              </th>
              <th className="px-4 py-3">Customer Name</th>
              <th className="px-4 py-3">GSTIN</th>
              <th
                className="cursor-pointer px-4 py-3 text-right hover:text-[#342B40]"
                onClick={() => toggleSort("taxable")}
              >
                <div className="flex items-center justify-end gap-1">
                  <span>Taxable Value (₹)</span>
                  <ArrowUpDown className="h-3 w-3 text-[#B8ADC2]" />
                </div>
              </th>
              <th className="px-4 py-3 text-right">IGST (₹)</th>
              <th className="px-4 py-3 text-right">CGST (₹)</th>
              <th className="px-4 py-3 text-right">SGST (₹)</th>
              <th className="px-4 py-3 text-center">Status</th>
            </tr>
          </thead>
          <tbody>
            {paginated.length === 0 ? (
              <tr>
                <td colSpan={10} className="py-12 text-center text-xs text-[#968BA2]">
                  No matching records found.
                </td>
              </tr>
            ) : (
              paginated.map((r) => {
                const isSelected = selectedIds.has(r.id);
                return (
                  <tr
                    key={r.id}
                    className={`border-b border-[#EEE8F4] transition-colors last:border-b-0 hover:bg-[#FCFBFE] ${
                      isSelected ? "bg-[#F7F4FA]" : "bg-white"
                    }`}
                  >
                    <td className="px-4 py-3">
                      <input
                        type="checkbox"
                        checked={isSelected}
                        onChange={() => toggleSelect(r.id)}
                        className="rounded border-[#D8CDE3] text-[#78608F] focus:ring-[#78608F]"
                        aria-label={`Select invoice ${r.invoiceNumber}`}
                      />
                    </td>
                    <td className="px-4 py-3 font-mono text-[13px] font-bold text-[#78608F]">
                      {r.invoiceNumber}
                    </td>
                    <td className="px-4 py-3 text-xs text-[#756184] whitespace-nowrap">
                      {r.invoiceDate}
                    </td>
                    <td className="px-4 py-3 font-medium text-[#342B40] max-w-[200px] truncate" title={r.customerName}>
                      {r.customerName}
                    </td>
                    <td className="px-4 py-3 font-mono text-xs font-semibold text-[#594C66]">
                      {r.gstin}
                    </td>
                    <td className="px-4 py-3 text-right font-semibold text-[#342B40] tabular-nums whitespace-nowrap">
                      {formatINR(r.taxableValue)}
                    </td>
                    <td className="px-4 py-3 text-right text-xs font-medium text-[#594C66] tabular-nums whitespace-nowrap">
                      {r.igst > 0 ? formatINR(r.igst) : "—"}
                    </td>
                    <td className="px-4 py-3 text-right text-xs font-medium text-[#594C66] tabular-nums whitespace-nowrap">
                      {r.cgst > 0 ? formatINR(r.cgst) : "—"}
                    </td>
                    <td className="px-4 py-3 text-right text-xs font-medium text-[#594C66] tabular-nums whitespace-nowrap">
                      {r.sgst > 0 ? formatINR(r.sgst) : "—"}
                    </td>
                    <td className="px-4 py-3 text-center whitespace-nowrap">
                      {r.statusBadge}
                    </td>
                  </tr>
                );
              })
            )}
          </tbody>
        </table>
      </div>

      {filtered.length > pageSize && (
        <ReconcilePaginationFooter
          page={currentPage}
          totalPages={totalPages}
          total={filtered.length}
          limit={pageSize}
          onPrev={() => setPage(Math.max(1, currentPage - 1))}
          onNext={() => setPage(Math.min(totalPages, currentPage + 1))}
          pageSize={pageSize}
          pageSizeOptions={[25, 50, 100, 250]}
          onPageSizeChange={(newSize) => {
            setPageSize(newSize);
            setPage(1);
          }}
        />
      )}
    </div>
  );
}

export function Gstr1ResultsView({
  result,
  onRunAgain,
  authToken,
  runId: runIdProp,
}: {
  result: Gstr1ReconcileResult;
  onRunAgain?: () => void;
  authToken?: string | null;
  runId?: string | null;
}) {
  const [tab, setTab] = useState<ResultsBucketTabId>("matched");
  const [viewMode, setViewMode] = useState<"table" | "cards">("table");
  const [reviewMode, setReviewMode] = useState(false);
  const [resumeSession, setResumeSession] = useState<{
    remainingCount: number;
    totalCount?: number;
    lastInvoiceId?: string | null;
    lastReviewedAt?: string;
  } | null>(null);
  const [excelBusy, setExcelBusy] = useState(false);
  const [pdfBusy, setPdfBusy] = useState(false);
  const [filesDropdownOpen, setFilesDropdownOpen] = useState(false);
  const filesDropdownRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!filesDropdownOpen) return;
    const handleClickOutside = (e: MouseEvent) => {
      if (
        filesDropdownRef.current &&
        !filesDropdownRef.current.contains(e.target as Node)
      ) {
        setFilesDropdownOpen(false);
      }
    };
    const handleKeyDown = (e: KeyboardEvent) => {
      if (e.key === "Escape") {
        setFilesDropdownOpen(false);
      }
    };
    document.addEventListener("mousedown", handleClickOutside);
    document.addEventListener("keydown", handleKeyDown);
    return () => {
      document.removeEventListener("mousedown", handleClickOutside);
      document.removeEventListener("keydown", handleKeyDown);
    };
  }, [filesDropdownOpen]);

  const uploadedFiles = useMemo(() => {
    const list: { label: string; filename: string }[] = [];
    if (result.meta?.sales_register_filename) {
      list.push({
        label: "Sales Register",
        filename: result.meta.sales_register_filename,
      });
    }
    if (result.meta?.gstr1_filename) {
      list.push({
        label: "GSTR-1",
        filename: result.meta.gstr1_filename,
      });
    }
    if (result.meta?.gstr3b_filename) {
      list.push({
        label: "GSTR-3B",
        filename: result.meta.gstr3b_filename,
      });
    }
    if (result.meta?.prior_gstr1_filename) {
      list.push({
        label: "Prior GSTR-1",
        filename: result.meta.prior_gstr1_filename,
      });
    }
    return list;
  }, [
    result.meta?.sales_register_filename,
    result.meta?.gstr1_filename,
    result.meta?.gstr3b_filename,
    result.meta?.prior_gstr1_filename,
  ]);

  const compactMetadataText = useMemo(() => {
    if (uploadedFiles.length === 0) {
      return "Sales Register · GSTR-1 · GSTR-3B";
    }
    const countPrefix = `${uploadedFiles.length} files analysed`;
    const names = uploadedFiles.map((f) => f.label).join(" · ");
    return `${countPrefix} · ${names}`;
  }, [uploadedFiles]);

  const summary = result.summary;

  const mismatchCounts = useMemo(
    () => countMismatchesByType(result.mismatches || []),
    [result.mismatches]
  );
  const reviewRows = useMemo(
    () =>
      filterReviewRequired(result.matched || [], result.mismatches || []),
    [result.matched, result.mismatches]
  );
  const g1m3Count = mismatchCounts.G1M3 || 0;

  const seriesWarnings = useMemo(
    () =>
      result.series_compliance_warnings ||
      (result.mismatches || []).filter(
        (m) =>
          m.mismatch_type === "G1M8_INVOICE_SERIES_ISSUE" ||
          m.mismatch_type === "G1M10_DOCUMENTS_ISSUED_SUMMARY" ||
          m.category === "compliance_warning"
      ),
    [result.series_compliance_warnings, result.mismatches]
  );
  const seriesWarningsCount =
    summary?.series_compliance_warning_count ?? seriesWarnings.length;

  const trueReconciliationMismatches = useMemo(
    () =>
      result.reconciliation_mismatches ||
      (result.mismatches || []).filter(
        (m) =>
          m.category === "reconciliation_mismatch" ||
          (!m.category &&
            m.mismatch_type !== "G1M8_INVOICE_SERIES_ISSUE" &&
            m.mismatch_type !== "G1M10_DOCUMENTS_ISSUED_SUMMARY" &&
            m.mismatch_type !== "G1M3_AMOUNT_MISMATCH" &&
            m.mismatch_severity !== "info")
      ),
    [result.reconciliation_mismatches, result.mismatches]
  );

  const reviewMismatches = useMemo(
    () =>
      result.review_required_items ||
      (result.mismatches || []).filter(
        (m) =>
          m.category === "review_required" ||
          (!m.category && m.mismatch_type === "G1M3_AMOUNT_MISMATCH")
      ),
    [result.review_required_items, result.mismatches]
  );

  const infoMismatches = useMemo(
    () =>
      result.informational_notices ||
      (result.mismatches || []).filter(
        (m) =>
          m.category === "info_notice" ||
          (!m.category && m.mismatch_severity === "info")
      ),
    [result.informational_notices, result.mismatches]
  );

  const resolvedRunId =
    runIdProp || result.run_id
      ? String(runIdProp || result.run_id)
      : null;
  const gstr1aWindow =
    result.gstr1a_window ?? summary.gstr1a_window ?? null;
  const gstr1aEligible = useMemo(
    () => filterGstr1aEligibleMismatches(result.mismatches || []),
    [result.mismatches]
  );
  const gstr1aSummaryHref = resolvedRunId
    ? `/reconcile/gstr1/gstr1a?run_id=${encodeURIComponent(resolvedRunId)}`
    : "/reconcile/gstr1/gstr1a";

  const extraInGstr1Count = summary.unmatched_gstr1_count;
  const fieldMismatchCount = g1m3Count;
  const invoiceLevelMatchCount =
    summary.invoice_level_match_count ?? summary.matched_count;
  const aggregateSourceCount = summary.aggregate_source_invoice_count ?? 0;
  const accountedSourceCount =
    summary.accounted_source_invoice_count ?? summary.matched_count;
  const coverageRate =
    typeof summary.coverage_percentage === "number"
      ? summary.coverage_percentage
      : summary.sr_total_records > 0
        ? Math.round((accountedSourceCount / summary.sr_total_records) * 1000) / 10
        : 100;
  const matchRate =
    summary.gstr1_total_records > 0
      ? Math.round(
          (invoiceLevelMatchCount / summary.gstr1_total_records) * 1000
        ) / 10
      : 0;

  const periodLabel =
    result.meta?.filing_period ||
    result.tie_out?.ret_period ||
    result.parse_diagnostics?.gstr1?.filing_period ||
    "—";

  const filingPeriodYyyyMm = toFilingPeriodYyyyMm(
    typeof periodLabel === "string" ? periodLabel : null
  );
  const filingHref = filingPeriodYyyyMm
    ? `/filing/gstr-1/${encodeURIComponent(filingPeriodYyyyMm)}${
        result.client_gstin_id
          ? `?client_gstin_id=${encodeURIComponent(result.client_gstin_id)}`
          : ""
      }`
    : "/filing/gstr-1";

  const savedViewStateRef = useRef<{ tab: ResultsBucketTabId; scrollY: number }>({
    tab: "matched",
    scrollY: 0,
  });

  const handleEnterReviewMode = () => {
    savedViewStateRef.current = {
      tab,
      scrollY: typeof window !== "undefined" ? window.scrollY : 0,
    };
    setReviewMode(true);
  };

  const handleExitReviewMode = () => {
    setReviewMode(false);
    setTab(savedViewStateRef.current.tab);
    setTimeout(() => {
      if (typeof window !== "undefined") {
        window.scrollTo({ top: savedViewStateRef.current.scrollY, behavior: "instant" });
      }
    }, 30);
  };

  const sessionKey = useMemo(
    () => generateReviewScopeKey(result, resolvedRunId),
    [result, resolvedRunId]
  );

  useEffect(() => {
    const stored = safeStorageGet<{
      remainingCount: number;
      totalCount?: number;
      lastInvoiceId?: string | null;
      lastReviewedAt?: string;
    } | null>(`${sessionKey}_session`, null);

    if (stored && typeof stored.remainingCount === "number" && stored.remainingCount > 0) {
      setResumeSession(stored);
    }
  }, [sessionKey]);

  const totalReviewItemsCount = useMemo(() => {
    const missing =
      summary.missing_in_gstr1_count ??
      (mismatchCounts.G1M1 || summary.unmatched_sr_count);
    return g1m3Count + missing + (extraInGstr1Count || 0);
  }, [g1m3Count, summary.missing_in_gstr1_count, mismatchCounts.G1M1, summary.unmatched_sr_count, extraInGstr1Count]);

  const handleExcel = () => {
    setExcelBusy(true);
    try {
      downloadGstr1ExcelReport(result);
    } finally {
      setExcelBusy(false);
    }
  };

  const handlePdf = async () => {
    setPdfBusy(true);
    try {
      await downloadGstr1PdfReport(result);
    } finally {
      setPdfBusy(false);
    }
  };

  // Convert matched data to table format
  const matchedTableData: TableRowData[] = useMemo(() => {
    return (result.matched || []).map((row, i) => {
      const sr = row.sr_record || {};
      const g1 = row.gstr1_record || {};
      const invNum = recordInvoiceNumber(sr) || recordInvoiceNumber(g1) || `INV-${i + 1}`;
      const invDate = String(sr.invoice_date || g1.invoice_date || "—");
      const custName = String(sr.recipient_name || g1.recipient_name || sr.customer_name || "—");
      const gstin = gstinDisplay(recordGstin(sr) || recordGstin(g1));
      const taxable = recordAmountRupees(sr) || (sr.taxable_amount_paise ? sr.taxable_amount_paise / 100 : 0);
      const igst = (sr.igst_paise ?? g1.igst_paise ?? 0) / 100;
      const cgst = (sr.cgst_paise ?? g1.cgst_paise ?? 0) / 100;
      const sgst = (sr.sgst_paise ?? g1.sgst_paise ?? 0) / 100;

      const badge = row.requires_human_review ? (
        <span className="inline-flex items-center rounded-full bg-[#FFF5DD] px-2.5 py-0.5 text-xs font-semibold text-[#97621C] border border-[#FDE7B2]">
          Review
        </span>
      ) : (
        <span className="inline-flex items-center rounded-full bg-[#E7F8EE] px-2.5 py-0.5 text-xs font-semibold text-[#237B51] border border-[#D1F2DD]">
          L{row.match_level ?? 1} · {row.confidence ?? 100}%
        </span>
      );

      return {
        id: `matched-${invNum}-${i}`,
        invoiceNumber: invNum,
        invoiceDate: invDate,
        customerName: custName,
        gstin,
        taxableValue: taxable,
        igst,
        cgst,
        sgst,
        statusBadge: badge,
      };
    });
  }, [result.matched]);

  // Convert review rows to table format
  const reviewTableData: TableRowData[] = useMemo(() => {
    return reviewRows.map((row, i) => {
      const sr = row.sr_record || {};
      const g1 = row.gstr1_record || {};
      const invNum = recordInvoiceNumber(sr) || recordInvoiceNumber(g1) || `INV-${i + 1}`;
      const invDate = String(sr.invoice_date || g1.invoice_date || "—");
      const custName = String(sr.recipient_name || g1.recipient_name || sr.customer_name || "—");
      const gstin = gstinDisplay(recordGstin(sr) || recordGstin(g1));
      const taxable = recordAmountRupees(sr) || (sr.taxable_amount_paise ? sr.taxable_amount_paise / 100 : 0);
      const igst = (sr.igst_paise ?? g1.igst_paise ?? 0) / 100;
      const cgst = (sr.cgst_paise ?? g1.cgst_paise ?? 0) / 100;
      const sgst = (sr.sgst_paise ?? g1.sgst_paise ?? 0) / 100;

      const badge = (
        <span className="inline-flex items-center rounded-full bg-[#FFF5DD] px-2.5 py-0.5 text-xs font-semibold text-[#97621C] border border-[#FDE7B2]">
          G1M3 · Review
        </span>
      );

      return {
        id: `review-${invNum}-${i}`,
        invoiceNumber: invNum,
        invoiceDate: invDate,
        customerName: custName,
        gstin,
        taxableValue: taxable,
        igst,
        cgst,
        sgst,
        statusBadge: badge,
      };
    });
  }, [reviewRows]);

  // Convert missing rows to table format
  const missingTableData: TableRowData[] = useMemo(() => {
    const list = (result.unmatched_sr || []).filter(
      (r) =>
        !r.mismatch_type ||
        r.mismatch_type === "G1M1_MISSING_INVOICE" ||
        (r as any).outcome_code === "G1M1"
    );
    return list.map((row, i) => {
      const rec = row.record || {};
      const invNum = recordInvoiceNumber(rec) || `INV-${i + 1}`;
      const invDate = String(rec.invoice_date || "—");
      const custName = String(rec.recipient_name || rec.customer_name || "—");
      const gstin = gstinDisplay(recordGstin(rec) || String(row.recipient_gstin || ""));
      const taxable = recordAmountRupees(rec) || (rec.taxable_amount_paise ? rec.taxable_amount_paise / 100 : 0);
      const igst = (rec.igst_paise ?? 0) / 100;
      const cgst = (rec.cgst_paise ?? 0) / 100;
      const sgst = (rec.sgst_paise ?? 0) / 100;

      const badge = (
        <span className="inline-flex items-center rounded-full bg-[#FEECEE] px-2.5 py-0.5 text-xs font-semibold text-[#9C3843] border border-[#FCD3D7]">
          G1M1 · Missing
        </span>
      );

      return {
        id: `missing-${invNum}-${i}`,
        invoiceNumber: invNum,
        invoiceDate: invDate,
        customerName: custName,
        gstin,
        taxableValue: taxable,
        igst,
        cgst,
        sgst,
        statusBadge: badge,
      };
    });
  }, [result.unmatched_sr]);

  // Convert extra rows to table format
  const extraTableData: TableRowData[] = useMemo(() => {
    return (result.unmatched_gstr1 || []).map((row, i) => {
      const rec = row.record || {};
      const invNum = recordInvoiceNumber(rec) || `INV-${i + 1}`;
      const invDate = String(rec.invoice_date || "—");
      const custName = String(rec.recipient_name || rec.customer_name || "—");
      const gstin = gstinDisplay(recordGstin(rec) || String(row.recipient_gstin || ""));
      const taxable = recordAmountRupees(rec) || (rec.taxable_amount_paise ? rec.taxable_amount_paise / 100 : 0);
      const igst = (rec.igst_paise ?? 0) / 100;
      const cgst = (rec.cgst_paise ?? 0) / 100;
      const sgst = (rec.sgst_paise ?? 0) / 100;

      const badge = (
        <span className="inline-flex items-center rounded-full bg-[#FFF5DD] px-2.5 py-0.5 text-xs font-semibold text-[#97621C] border border-[#FDE7B2]">
          G1M2 · Extra
        </span>
      );

      return {
        id: `extra-${invNum}-${i}`,
        invoiceNumber: invNum,
        invoiceDate: invDate,
        customerName: custName,
        gstin,
        taxableValue: taxable,
        igst,
        cgst,
        sgst,
        statusBadge: badge,
      };
    });
  }, [result.unmatched_gstr1]);

  if (reviewMode) {
    return (
      <Gstr1ReviewWorkspace
        result={result}
        periodLabel={typeof periodLabel === "string" ? periodLabel : "Current Period"}
        runId={resolvedRunId}
        onExit={handleExitReviewMode}
        initialInvoiceId={resumeSession?.lastInvoiceId}
      />
    );
  }

  // Diagnostic chip styling helper
  const renderDiagnosticChip = (code: string, count: number) => {
    let chipClass = "bg-white text-[#51465E] border border-[#E8E0F1]";
    let codeClass = "text-[#78608F] font-bold";
    let countClass = "text-[#756184] font-semibold";

    if (code === "G1M1") {
      chipClass = "bg-[#FEECEE] text-[#9C3843] border border-[#FCD3D7]";
      codeClass = "text-[#9C3843] font-bold";
      countClass = "text-[#BE555E] font-semibold";
    } else if (code === "G1M2" || code === "G1M3" || code === "G1D2") {
      chipClass = "bg-[#FFF5DD] text-[#97621C] border border-[#FDE7B2]";
      codeClass = "text-[#97621C] font-bold";
      countClass = "text-[#A56B26] font-semibold";
    } else if (code === "G1D1" || code === "G1C1") {
      chipClass = "bg-[#F0EAF7] text-[#554260] border border-[#E8E0F1]";
      codeClass = "text-[#554260] font-bold";
      countClass = "text-[#756184] font-semibold";
    }

    return (
      <span
        key={code}
        className={`inline-flex items-center gap-1.5 rounded-full px-3 py-1 text-xs shadow-xs transition-shadow hover:shadow-sm ${chipClass}`}
      >
        <span className={codeClass}>{code}</span>
        <span className={countClass}>{count.toLocaleString("en-IN")}</span>
      </span>
    );
  };

  // Tab counts
  const tabCountsRecord: Record<ResultsBucketTabId, number> = {
    matched: invoiceLevelMatchCount,
    review_required: summary.review_required_count ?? g1m3Count,
    unmatched_sr:
      summary.missing_in_gstr1_count ??
      (mismatchCounts.G1M1 || summary.unmatched_sr_count),
    unmatched_gstr1: mismatchCounts.G1M2 || summary.unmatched_gstr1_count,
    series_warnings: seriesWarningsCount,
    tie_out: summary.tie_out_variance_count,
    documents_issued:
      summary.documents_issued_series_count ??
      result.documents_issued?.total_series ??
      0,
    diagnostics:
      (result.parse_diagnostics?.sr?.skipped_rows || 0) +
      (result.parse_diagnostics?.gstr1?.total_skipped || 0),
    itc_on_hold: 0,
    duplicate_entry: 0,
    unmatched_notes: 0,
    risk: 0,
    itc: 0,
    rule37: 0,
    section17: 0,
    rcm: 0,
    gstr3b: 0,
    followup: 0,
    ims: 0,
    einvoice: 0,
  };

  return (
    <div className={`${styles.results} box-border w-full min-w-0 space-y-4 px-6 py-5 pb-36`}>
      {/* 1. Context & Header Card */}
      <div className={styles.contextCard}>
        <div className="flex flex-wrap items-start justify-between gap-4">
          <div className="min-w-0">
            <p className="text-[10px] font-bold uppercase tracking-[1.8px] text-[#78608F]">
              GSTR-1 Results
            </p>
            <h1 className="mt-1 text-2xl font-bold tracking-tight text-[#342B40]">
              {periodLabel.startsWith("20") ? `Period ${periodLabel}` : periodLabel}
            </h1>

            {/* Compact Metadata Line + View files dropdown */}
            <div className="relative mt-1.5 flex flex-wrap items-center gap-x-2 gap-y-1 text-[13px] text-[#756184]">
              <span>{compactMetadataText}</span>
              {uploadedFiles.length > 0 && (
                <div className="relative inline-block" ref={filesDropdownRef}>
                  <button
                    type="button"
                    onClick={() => setFilesDropdownOpen((prev) => !prev)}
                    aria-expanded={filesDropdownOpen}
                    aria-haspopup="dialog"
                    className="inline-flex items-center gap-1 rounded px-2 py-0.5 text-xs font-semibold text-[#78608F] hover:bg-[#F0EAF7] transition-colors"
                  >
                    <span>View files</span>
                    <ChevronDown
                      className={`h-3 w-3 transition-transform duration-150 ${
                        filesDropdownOpen ? "rotate-180" : ""
                      }`}
                    />
                  </button>

                  {filesDropdownOpen && (
                    <div
                      role="dialog"
                      aria-label="Uploaded files for reconciliation"
                      className="absolute left-0 top-full z-50 mt-1.5 w-80 max-w-[calc(100vw-2rem)] sm:w-96 rounded-xl border border-[#E8E0F1] bg-white p-4 shadow-lg ring-1 ring-black/5"
                    >
                      <div className="flex items-center justify-between border-b border-[#EEE8F4] pb-2">
                        <span className="text-xs font-bold text-[#342B40]">
                          Uploaded Files ({uploadedFiles.length})
                        </span>
                        <button
                          type="button"
                          onClick={() => setFilesDropdownOpen(false)}
                          className="rounded p-1 text-[#968BA2] hover:bg-[#F0EAF7] hover:text-[#342B40]"
                          aria-label="Close"
                        >
                          <X className="h-3.5 w-3.5" />
                        </button>
                      </div>
                      <div className="mt-2.5 space-y-2 text-xs">
                        {uploadedFiles.map((f) => (
                          <div
                            key={f.label}
                            className="rounded-lg border border-[#EEE8F4] bg-[#FAF9FC] p-2.5"
                          >
                            <span className="text-[10px] font-bold uppercase tracking-wider text-[#78608F]">
                              {f.label}
                            </span>
                            <div
                              className="mt-1 font-mono text-[11px] text-[#342B40] break-all select-all leading-relaxed"
                              title={f.filename}
                            >
                              {f.filename}
                            </div>
                          </div>
                        ))}
                      </div>
                    </div>
                  )}
                </div>
              )}
            </div>

            {/* Status notification pills row */}
            <div className="mt-3 flex flex-wrap items-center gap-2">
              {!summary.tie_out_clean ? (
                <span className="inline-flex items-center gap-1.5 rounded-full bg-[#FFF5DD] px-3 py-1 text-[11px] font-semibold text-[#97621C] border border-[#FDE7B2]">
                  <AlertTriangle className="h-3.5 w-3.5" />
                  GSTR-1 vs 3B variances need review
                </span>
              ) : (
                <span className="inline-flex items-center gap-1.5 rounded-full bg-[#E7F8EE] px-3 py-1 text-[11px] font-semibold text-[#237B51] border border-[#D1F2DD]">
                  <Check className="h-3.5 w-3.5" />
                  Tie-out clean
                </span>
              )}

              {summary.amendment_detection_skipped ? (
                <span className="inline-flex items-center gap-1.5 rounded-full bg-[#F0EAF7] px-3 py-1 text-[11px] font-medium text-[#554260] border border-[#E8E0F1]">
                  <RotateCcw className="h-3.5 w-3.5 text-[#78608F]" />
                  Amendment detection skipped — prior GSTR-1 not provided
                </span>
              ) : (summary.amendment_count || 0) > 0 ? (
                <span className="inline-flex items-center gap-1.5 rounded-full bg-[#FFF5DD] px-3 py-1 text-[11px] font-semibold text-[#97621C] border border-[#FDE7B2]">
                  {(summary.amendment_count || 0).toLocaleString("en-IN")}{" "}
                  amendment{(summary.amendment_count || 0) === 1 ? "" : "s"}{" "}
                  (9A/9B/9C)
                </span>
              ) : (
                <span className="inline-flex items-center gap-1.5 rounded-full bg-[#E7F8EE] px-3 py-1 text-[11px] font-semibold text-[#237B51] border border-[#D1F2DD]">
                  No amendments vs prior GSTR-1
                </span>
              )}

              {summary.b2cs_reconciliation_status === "MATCHED" ? (
                <span className="inline-flex items-center gap-1.5 rounded-full bg-[#E7F8EE] px-3 py-1 text-[11px] font-semibold text-[#237B51] border border-[#D1F2DD]">
                  B2CS aggregate matched ({aggregateSourceCount.toLocaleString("en-IN")} invoices)
                </span>
              ) : summary.b2cs_reconciliation_status === "MISMATCH" ? (
                <span className="inline-flex items-center gap-1.5 rounded-full bg-[#FFF5DD] px-3 py-1 text-[11px] font-semibold text-[#97621C] border border-[#FDE7B2]">
                  B2CS aggregate mismatch
                </span>
              ) : null}

              {gstr1aEligible.length > 0 ? (
                <Link
                  href={gstr1aSummaryHref}
                  className="inline-flex items-center gap-1.5 rounded-full bg-[#342B40] px-3 py-1 text-[11px] font-semibold text-white shadow-xs transition-colors hover:bg-[#251E2F]"
                >
                  <Layers className="h-3.5 w-3.5" />
                  GSTR-1A batch · {gstr1aEligible.length.toLocaleString("en-IN")} eligible
                </Link>
              ) : null}
            </div>
          </div>

          {/* Action buttons top-right */}
          <div className="flex shrink-0 items-center gap-2">
            <button
              type="button"
              onClick={handleEnterReviewMode}
              className={styles.actionBtnPrimary}
            >
              <span>Start review</span>
              <span className="rounded-full bg-white/20 px-1.5 py-0.2 text-[10px] font-bold tabular-nums">
                {totalReviewItemsCount.toLocaleString("en-IN")}
              </span>
              <span>→</span>
            </button>
            <button
              type="button"
              disabled={excelBusy}
              className={styles.actionBtnLight}
              onClick={handleExcel}
            >
              {excelBusy ? (
                <Loader2 className="h-3.5 w-3.5 animate-spin" />
              ) : (
                <FileSpreadsheet className="h-3.5 w-3.5 text-[#78608F]" />
              )}
              <span>Excel</span>
            </button>
            <button
              type="button"
              disabled={pdfBusy}
              className={styles.actionBtnLight}
              onClick={() => void handlePdf()}
            >
              {pdfBusy ? (
                <Loader2 className="h-3.5 w-3.5 animate-spin" />
              ) : (
                <FileText className="h-3.5 w-3.5 text-[#78608F]" />
              )}
              <span>PDF</span>
            </button>
          </div>
        </div>

        {/* Resume Review Banner if prior session in progress */}
        {resumeSession && resumeSession.remainingCount > 0 && (
          <div className="mt-4 flex flex-wrap items-center justify-between gap-3 rounded-xl border border-[#E8E0F1] bg-[#FAF8FC] p-3.5 shadow-xs">
            <div className="flex items-center gap-3">
              <div className="flex h-8 w-8 items-center justify-center rounded-lg bg-[#78608F] text-white">
                <RotateCcw className="h-4 w-4" />
              </div>
              <div>
                <h4 className="text-xs font-bold text-[#342B40]">
                  Continue review
                </h4>
                <p className="text-xs text-[#756184]">
                  <strong className="font-semibold text-[#554260]">{resumeSession.remainingCount} items remaining</strong>
                  {resumeSession.lastInvoiceId ? " · Session saved" : ""}
                </p>
              </div>
            </div>
            <button
              type="button"
              onClick={handleEnterReviewMode}
              className="inline-flex items-center gap-1.5 rounded-[7px] bg-[#342B40] px-3.5 py-1.5 text-xs font-semibold text-white shadow-xs hover:bg-[#251E2F] transition-colors"
            >
              Resume review →
            </button>
          </div>
        )}
      </div>

      {/* 2. Overview KPI Cards (5 Cards) */}
      <div className="grid grid-cols-2 gap-3.5 sm:grid-cols-3 lg:grid-cols-5">
        {/* Card 1: Sales Register */}
        <div className={styles.kpiCard}>
          <div className="flex items-center justify-between">
            <span className="text-[10px] font-bold uppercase tracking-[1.4px] text-[#968BA2]">
              Sales Register
            </span>
            <div className="flex h-7 w-7 items-center justify-center rounded-full bg-[#F0EAF7] text-[#78608F]">
              <FileText className="h-3.5 w-3.5" />
            </div>
          </div>
          <div className="mt-2 text-[30px] sm:text-[34px] font-black leading-none text-[#342B40] tabular-nums">
            {summary.sr_total_records.toLocaleString("en-IN")}
          </div>
          <div className="mt-2 text-[11px] font-medium text-[#968BA2]">
            Total source records
          </div>
        </div>

        {/* Card 2: Matched */}
        <div className={styles.kpiCard}>
          <div className="flex items-center justify-between">
            <span className="text-[10px] font-bold uppercase tracking-[1.4px] text-[#968BA2]">
              Matched
            </span>
            <div className="flex h-7 w-7 items-center justify-center rounded-full bg-[#E7F8EE] text-[#398461]">
              <CheckCircle className="h-3.5 w-3.5" />
            </div>
          </div>
          <div className="mt-2 text-[30px] sm:text-[34px] font-black leading-none text-[#398461] tabular-nums">
            {invoiceLevelMatchCount.toLocaleString("en-IN")}
          </div>
          <div className="mt-2 text-[11px] font-medium text-[#968BA2]">
            {aggregateSourceCount > 0
              ? `${aggregateSourceCount.toLocaleString("en-IN")} B2CS covered`
              : `${matchRate}% of GSTR-1`}
          </div>
        </div>

        {/* Card 3: Review Required */}
        <div className={styles.kpiCard}>
          <div className="flex items-center justify-between">
            <span className="text-[10px] font-bold uppercase tracking-[1.4px] text-[#968BA2]">
              Review Required
            </span>
            <div className="flex h-7 w-7 items-center justify-center rounded-full bg-[#FFF5DD] text-[#A56B26]">
              <AlertTriangle className="h-3.5 w-3.5" />
            </div>
          </div>
          <div className="mt-2 text-[30px] sm:text-[34px] font-black leading-none text-[#A56B26] tabular-nums">
            {g1m3Count.toLocaleString("en-IN")}
          </div>
          <div className="mt-2 text-[11px] font-medium text-[#968BA2]">
            G1M3 · taxable / PoS
          </div>
        </div>

        {/* Card 4: Missing in GSTR-1 */}
        <div className={styles.kpiCard}>
          <div className="flex items-center justify-between">
            <span className="text-[10px] font-bold uppercase tracking-[1.4px] text-[#968BA2]">
              Missing in GSTR-1
            </span>
            <div className="flex h-7 w-7 items-center justify-center rounded-full bg-[#FEECEE] text-[#BE555E]">
              <XCircle className="h-3.5 w-3.5" />
            </div>
          </div>
          <div className="mt-2 text-[30px] sm:text-[34px] font-black leading-none text-[#BE555E] tabular-nums">
            {(
              summary.missing_in_gstr1_count ??
              mismatchCounts.G1M1 ??
              summary.unmatched_sr_count
            ).toLocaleString("en-IN")}
          </div>
          <div className="mt-2 text-[11px] font-medium text-[#968BA2]">
            G1M1 · under-reporting
          </div>
        </div>

        {/* Card 5: Extra · Field issues */}
        <div className={styles.kpiCard}>
          <div className="flex items-center justify-between">
            <span className="text-[10px] font-bold uppercase tracking-[1.4px] text-[#968BA2]">
              Extra · Field issues
            </span>
            <div className="flex h-7 w-7 items-center justify-center rounded-full bg-[#F0EAF7] text-[#78608F]">
              <FileSpreadsheet className="h-3.5 w-3.5" />
            </div>
          </div>
          <div className="mt-1.5 space-y-1">
            <div className="flex items-baseline justify-between gap-2">
              <span className="text-[11px] text-[#756184]">Extra in GSTR-1</span>
              <span className={`text-base font-bold tabular-nums ${extraInGstr1Count > 0 ? "text-[#A56B26]" : "text-[#968BA2]"}`}>
                {extraInGstr1Count.toLocaleString("en-IN")}
              </span>
            </div>
            <div className="flex items-baseline justify-between gap-2">
              <span className="text-[11px] text-[#756184]">Field mismatches</span>
              <span className={`text-base font-bold tabular-nums ${fieldMismatchCount > 0 ? "text-[#A56B26]" : "text-[#968BA2]"}`}>
                {fieldMismatchCount.toLocaleString("en-IN")}
              </span>
            </div>
          </div>
          <div className="mt-1 text-[10.5px] font-medium text-[#968BA2]">
            Extra = G1M2 · Field = G1M3
          </div>
        </div>
      </div>

      {/* Coverage Progress Bar */}
      <div className="flex w-full items-center gap-3 rounded-xl border border-[#E8E0F1] bg-white px-4 py-2.5 shadow-xs">
        <div className="min-w-0 flex-1 overflow-hidden">
          <div className="h-2 w-full overflow-hidden rounded-full bg-[#EAE4F2]">
            <div
              className="h-full rounded-full bg-[#78608F] transition-all duration-300"
              style={{ width: `${Math.min(100, Math.max(0, coverageRate))}%` }}
            />
          </div>
        </div>
        <p className="shrink-0 whitespace-nowrap text-xs font-medium text-[#756184]">
          Accounted: <strong className="text-[#342B40]">{accountedSourceCount.toLocaleString("en-IN")}</strong> / {summary.sr_total_records.toLocaleString("en-IN")} ({coverageRate}%)
        </p>
        <span className="inline-flex items-center rounded-full bg-[#342B40] px-2.5 py-0.5 text-xs font-bold text-white shadow-xs">
          {coverageRate}%
        </span>
      </div>

      {/* 3. Diagnostic Code Chips Strip */}
      {Object.keys(mismatchCounts).length > 0 && (
        <div className="flex flex-wrap items-center gap-2">
          {(
            [
              "G1M1",
              "G1M2",
              "G1M3",
              "G1M6",
              "G1M8",
              "G1M10",
              "G1M11",
              "G1D1",
              "G1D2",
              "G1C1",
            ] as const
          ).map((code) => {
            const count = mismatchCounts[code];
            return count ? renderDiagnosticChip(code, count) : null;
          })}
        </div>
      )}

      {/* 4. Results Tabs & Main Workspace Card */}
      <div className={styles.workspaceCard}>
        {/* Custom Tab List Header matching GSTR-2B styling */}
        <div className="flex flex-wrap items-center justify-between border-b border-[#EEE8F4] bg-white pr-4">
          <nav className={styles.tabList} role="tablist" aria-label="GSTR-1 results tabs">
            {SALES_RESULTS_BUCKET_TABS.map(({ id, label }) => {
              const isActive = tab === id;
              const count = tabCountsRecord[id];

              let badgeTone = "bg-[#F0EAF7] text-[#554260] border border-[#E8E0F1]";
              if (id === "matched" && count > 0) {
                badgeTone = "bg-[#E7F8EE] text-[#237B51] border border-[#D1F2DD]";
              } else if ((id === "review_required" || id === "unmatched_gstr1" || id === "tie_out") && count > 0) {
                badgeTone = "bg-[#FFF5DD] text-[#97621C] border border-[#FDE7B2]";
              } else if (id === "unmatched_sr" && count > 0) {
                badgeTone = "bg-[#FEECEE] text-[#9C3843] border border-[#FCD3D7]";
              } else if (count === 0) {
                badgeTone = "bg-[#F8F6FA] text-[#968BA2] border border-[#EEE8F4]";
              }

              return (
                <button
                  key={id}
                  type="button"
                  role="tab"
                  aria-selected={isActive}
                  onClick={() => setTab(id)}
                  className={`${styles.tabBtn} ${isActive ? styles.tabBtnActive : ""}`}
                >
                  <span>{label}</span>
                  {count != null && (
                    <span
                      className={`rounded-full px-2 py-0.5 text-[11px] font-semibold tabular-nums ${badgeTone}`}
                    >
                      {count.toLocaleString("en-IN")}
                    </span>
                  )}
                </button>
              );
            })}
          </nav>

          {/* Quick toggle view and download report button */}
          <div className="flex items-center gap-2 py-2">
            {(tab === "matched" || tab === "review_required" || tab === "unmatched_sr" || tab === "unmatched_gstr1") && (
              <div className="flex items-center rounded-lg border border-[#E5DCEE] bg-[#FAF8FC] p-0.5">
                <button
                  type="button"
                  onClick={() => setViewMode("table")}
                  className={`inline-flex items-center gap-1 rounded-md px-2.5 py-1 text-xs font-semibold transition-colors ${
                    viewMode === "table"
                      ? "bg-white text-[#342B40] shadow-xs"
                      : "text-[#756184] hover:text-[#342B40]"
                  }`}
                  title="Table view"
                >
                  <TableIcon className="h-3.5 w-3.5" />
                  <span>Table</span>
                </button>
                <button
                  type="button"
                  onClick={() => setViewMode("cards")}
                  className={`inline-flex items-center gap-1 rounded-md px-2.5 py-1 text-xs font-semibold transition-colors ${
                    viewMode === "cards"
                      ? "bg-white text-[#342B40] shadow-xs"
                      : "text-[#756184] hover:text-[#342B40]"
                  }`}
                  title="Card view"
                >
                  <LayoutGrid className="h-3.5 w-3.5" />
                  <span>Cards</span>
                </button>
              </div>
            )}

            <button
              type="button"
              disabled={pdfBusy}
              className="inline-flex items-center gap-1.5 rounded-[7px] border border-[#E5DCEE] bg-white px-3 py-1.5 text-xs font-semibold text-[#554260] hover:bg-[#FAF8FC] transition-colors shadow-xs disabled:opacity-50"
              onClick={() => void handlePdf()}
            >
              {pdfBusy ? (
                <Loader2 className="h-3.5 w-3.5 animate-spin" />
              ) : (
                <FileText className="h-3.5 w-3.5 text-[#78608F]" />
              )}
              <span>Report PDF</span>
            </button>
          </div>
        </div>

        {/* Tab Content Panes */}
        <div className="p-6">
          {tab === "matched" && (
            <div className="space-y-4">
              <div className="flex items-center justify-between">
                <div>
                  <h2 className="text-[15px] font-bold tracking-tight text-[#342B40]">
                    Matched invoices{" "}
                    <span className="text-xs font-semibold text-[#968BA2]">
                      ({summary.matched_count.toLocaleString("en-IN")} records)
                    </span>
                  </h2>
                  <p className="mt-0.5 text-xs text-[#756184]">
                    Sales Register entries reconciled with GSTR-1 filings.
                  </p>
                </div>
              </div>

              {viewMode === "table" ? (
                <Gstr1InvoicesTable
                  rows={matchedTableData}
                  emptyTitle="No matched invoices"
                />
              ) : (
                <MatchedCards
                  rows={result.matched || []}
                  emptyTitle="No matched invoices"
                  emptyDescription="No Sales Register rows linked to GSTR-1 for this period."
                />
              )}
            </div>
          )}

          {tab === "review_required" && (
            <div className="space-y-4">
              <div>
                <h2 className="text-[15px] font-bold tracking-tight text-[#342B40]">
                  Review Required{" "}
                  <span className="text-xs font-semibold text-[#968BA2]">
                    ({(summary.review_required_count ?? g1m3Count).toLocaleString("en-IN")} records)
                  </span>
                </h2>
                <p className="mt-0.5 text-xs text-[#756184]">
                  Matched invoices with taxable value, tax amount, PoS, or tax-structure differences (G1M3).
                </p>
              </div>

              {viewMode === "table" ? (
                <Gstr1InvoicesTable
                  rows={reviewTableData}
                  emptyTitle="Nothing needs review"
                />
              ) : (
                <MatchedCards
                  rows={reviewRows}
                  emptyTitle="Nothing needs review"
                  emptyDescription="No G1M3 amount or PoS mismatches for this period."
                />
              )}
            </div>
          )}

          {tab === "unmatched_sr" && (
            <div className="space-y-4">
              <div className="flex flex-wrap items-center justify-between gap-3">
                <div>
                  <h2 className="text-[15px] font-bold tracking-tight text-[#342B40]">
                    Missing in GSTR-1{" "}
                    <span className="text-xs font-semibold text-[#968BA2]">
                      (
                      {(
                        summary.missing_in_gstr1_count ??
                        (mismatchCounts.G1M1 || summary.unmatched_sr_count)
                      ).toLocaleString("en-IN")}{" "}
                      records)
                    </span>
                  </h2>
                  <p className="mt-0.5 text-xs text-[#756184]">
                    Invoices in Sales Register that were not found in GSTR-1 (G1M1 — under-reporting risk).
                  </p>
                </div>

                {((summary.duplicate_postings_count ?? 0) > 0 ||
                  (summary.cancelled_reissued_count ?? 0) > 0) && (
                  <div className="flex flex-wrap items-center gap-2 text-xs">
                    {(summary.duplicate_postings_count ?? 0) > 0 && (
                      <span className="rounded-full bg-[#FFF5DD] px-2.5 py-0.5 font-semibold text-[#97621C] border border-[#FDE7B2]">
                        {summary.duplicate_postings_count} duplicate postings quarantined
                      </span>
                    )}
                    {(summary.cancelled_reissued_count ?? 0) > 0 && (
                      <span className="rounded-full bg-[#F0EAF7] px-2.5 py-0.5 font-semibold text-[#554260] border border-[#E8E0F1]">
                        {summary.cancelled_reissued_count} cancelled/reissued accounted
                      </span>
                    )}
                  </div>
                )}
              </div>

              {viewMode === "table" ? (
                <Gstr1InvoicesTable
                  rows={missingTableData}
                  emptyTitle="No missing invoices"
                />
              ) : (
                <UnmatchedCards
                  rows={(result.unmatched_sr || []).filter(
                    (r) =>
                      !r.mismatch_type ||
                      r.mismatch_type === "G1M1_MISSING_INVOICE" ||
                      (r as any).outcome_code === "G1M1"
                  )}
                  emptyTitle="No missing invoices"
                  gstr1aWindow={gstr1aWindow}
                />
              )}
            </div>
          )}

          {tab === "unmatched_gstr1" && (
            <div className="space-y-4">
              <div>
                <h2 className="text-[15px] font-bold tracking-tight text-[#342B40]">
                  Extra in GSTR-1{" "}
                  <span className="text-xs font-semibold text-[#968BA2]">
                    (
                    {(
                      mismatchCounts.G1M2 || summary.unmatched_gstr1_count
                    ).toLocaleString("en-IN")}{" "}
                    records)
                  </span>
                </h2>
                <p className="mt-0.5 text-xs text-[#756184]">
                  Invoices filed in GSTR-1 with no matching Sales Register entry (G1M2).
                </p>
              </div>

              {viewMode === "table" ? (
                <Gstr1InvoicesTable
                  rows={extraTableData}
                  emptyTitle="No extra GSTR-1 invoices"
                />
              ) : (
                <UnmatchedCards
                  rows={result.unmatched_gstr1 || []}
                  emptyTitle="No extra GSTR-1 invoices"
                  gstr1aWindow={gstr1aWindow}
                />
              )}
            </div>
          )}

          {tab === "series_warnings" && (
            <div className="space-y-4">
              <div>
                <h2 className="text-[15px] font-bold tracking-tight text-[#342B40]">
                  Invoice Series / Compliance Warnings{" "}
                  <span className="text-xs font-semibold text-[#968BA2]">
                    ({seriesWarningsCount.toLocaleString("en-IN")})
                  </span>
                </h2>
                <p className="mt-0.5 text-xs text-[#756184]">
                  Statutory serial numbering continuity (Rule 46 CGST / G1M8) and Table 13 documentation checks.
                </p>
              </div>

              {seriesWarnings.length === 0 ? (
                <EmptyTableState
                  title="No series or compliance warnings"
                  description="All invoice series are continuous without unexplained numeric gaps or duplicate numbers."
                />
              ) : (
                <ul className="space-y-3">
                  {seriesWarnings.map((m, i) => (
                    <li
                      key={`${m.mismatch_type}-${i}`}
                      className="rounded-xl border border-[#E8E0F1] bg-white p-4 shadow-xs"
                    >
                      <div className="flex flex-wrap items-center gap-2">
                        <TypePill type={m.mismatch_type} />
                        <SeverityPill severity={m.mismatch_severity} />
                        <span className="rounded-full bg-[#F0EAF7] px-2.5 py-0.5 text-[11px] font-semibold text-[#554260] border border-[#E8E0F1]">
                          Compliance Check
                        </span>
                        <span className="text-[13px] font-bold text-[#342B40]">
                          {m.decision_what || m.invoice_number || "Series Warning"}
                        </span>
                      </div>

                      {m.decision_why && (
                        <p className="mt-2 text-xs text-[#594C66] leading-relaxed">
                          {m.decision_why}
                        </p>
                      )}

                      {m.decision_next && (
                        <div className="mt-2.5 rounded-lg border border-[#FDE7B2] bg-[#FFF5DD] p-2.5 text-xs text-[#97621C]">
                          <span className="font-bold">Next step: </span>
                          <span>{m.decision_next}</span>
                        </div>
                      )}
                    </li>
                  ))}
                </ul>
              )}
            </div>
          )}

          {tab === "tie_out" && (
            <div className="space-y-6">
              <Gstr1TieOutPanel
                tieOut={result.tie_out || {}}
                clientName={result.meta?.client_name?.trim() || ""}
                clientGstin={
                  result.parse_diagnostics?.gstr1?.filing_gstin?.trim() || ""
                }
              />
              {resolvedRunId && authToken ? (
                <AuditObservationsPanel
                  runId={resolvedRunId}
                  authToken={authToken}
                  refreshKey={0}
                />
              ) : (
                <div className="rounded-xl border border-[#E8E0F1] bg-[#FAF8FC] p-4 text-xs text-[#756184]">
                  {resolvedRunId
                    ? "Sign in to load audit observations."
                    : "Audit observations require this run to be linked to a client."}
                </div>
              )}
            </div>
          )}

          {tab === "documents_issued" && (
            <Gstr1DocumentsIssuedPanel
              documentsIssued={result.documents_issued}
            />
          )}

          {tab === "diagnostics" && (
            <div className="space-y-6">
              <h2 className="text-[15px] font-bold tracking-tight text-[#342B40]">
                Parse Diagnostics
              </h2>
              <div className="grid gap-4 lg:grid-cols-2">
                <div className="rounded-xl border border-[#E8E0F1] bg-[#FAF9FC] p-4">
                  <p className="text-[10px] font-bold uppercase tracking-[1.8px] text-[#78608F]">
                    Sales Register
                  </p>
                  <dl className="mt-3 space-y-2 text-xs">
                    <div className="flex justify-between">
                      <dt className="text-[#756184]">Valid rows</dt>
                      <dd className="font-bold tabular-nums text-[#342B40]">
                        {result.parse_diagnostics?.sr?.valid_rows ?? "—"}
                      </dd>
                    </div>
                    <div className="flex justify-between">
                      <dt className="text-[#756184]">Skipped</dt>
                      <dd className="font-bold tabular-nums text-[#342B40]">
                        {result.parse_diagnostics?.sr?.skipped_rows ?? "—"}
                      </dd>
                    </div>
                    <div className="flex justify-between">
                      <dt className="text-[#756184]">Source</dt>
                      <dd className="font-semibold text-[#342B40]">
                        {result.parse_diagnostics?.sr?.source_software || "—"}
                      </dd>
                    </div>
                  </dl>
                  {(result.parse_diagnostics?.sr?.warnings || []).length > 0 && (
                    <ul className="mt-3 space-y-1 text-xs text-[#97621C]">
                      {(result.parse_diagnostics?.sr?.warnings || []).map((w) => (
                        <li key={w}>{w}</li>
                      ))}
                    </ul>
                  )}
                </div>

                <div className="rounded-xl border border-[#E8E0F1] bg-[#FAF9FC] p-4">
                  <p className="text-[10px] font-bold uppercase tracking-[1.8px] text-[#78608F]">
                    GSTR-1
                  </p>
                  <dl className="mt-3 space-y-2 text-xs">
                    <div className="flex justify-between">
                      <dt className="text-[#756184]">Parsed</dt>
                      <dd className="font-bold tabular-nums text-[#342B40]">
                        {result.parse_diagnostics?.gstr1?.total_parsed ?? "—"}
                      </dd>
                    </div>
                    <div className="flex justify-between">
                      <dt className="text-[#756184]">Skipped</dt>
                      <dd className="font-bold tabular-nums text-[#342B40]">
                        {result.parse_diagnostics?.gstr1?.total_skipped ?? "—"}
                      </dd>
                    </div>
                    <div className="flex justify-between">
                      <dt className="text-[#756184]">Filing GSTIN</dt>
                      <dd className="font-mono text-xs font-semibold text-[#342B40]">
                        {result.parse_diagnostics?.gstr1?.filing_gstin || "—"}
                      </dd>
                    </div>
                  </dl>
                  {result.parse_diagnostics?.gstr1?.section_counts && (
                    <div className="mt-3 flex flex-wrap gap-1.5">
                      {Object.entries(
                        result.parse_diagnostics.gstr1.section_counts
                      ).map(([sec, n]) => (
                        <span
                          key={sec}
                          className="rounded-full bg-white px-2.5 py-0.5 text-[11px] font-semibold text-[#554260] border border-[#E8E0F1]"
                        >
                          {sec}: {n}
                        </span>
                      ))}
                    </div>
                  )}
                </div>
              </div>

              {/* Classified Findings Breakdown */}
              <div className="mt-6 space-y-4">
                <div className="flex items-center justify-between border-b border-[#EEE8F4] pb-2">
                  <p className="text-[11px] font-bold uppercase tracking-wider text-[#78608F]">
                    Classified Findings Breakdown
                  </p>
                  {gstr1aEligible.length > 0 && (
                    <Link
                      href={gstr1aSummaryHref}
                      className="text-xs font-semibold text-[#78608F] hover:underline"
                    >
                      Open GSTR-1A summary →
                    </Link>
                  )}
                </div>

                {/* Reconciliation Mismatches */}
                <div className="space-y-2">
                  <div className="flex items-center gap-2">
                    <span className="h-2 w-2 rounded-full bg-[#BE555E]" />
                    <h3 className="text-xs font-bold text-[#342B40]">
                      Reconciliation Mismatches ({trueReconciliationMismatches.length})
                    </h3>
                  </div>
                  {trueReconciliationMismatches.length === 0 ? (
                    <p className="text-xs text-[#968BA2] italic">No reconciliation mismatches found.</p>
                  ) : (
                    <ul className="space-y-2">
                      {trueReconciliationMismatches.map((m, i) => (
                        <li
                          key={`recon-${m.mismatch_type}-${i}`}
                          className="rounded-xl border border-[#FCD3D7] bg-[#FEECEE]/40 px-3.5 py-2.5"
                        >
                          <div className="flex flex-wrap items-center gap-2">
                            <TypePill type={m.mismatch_type} />
                            <SeverityPill severity={m.mismatch_severity} />
                            <span className="text-xs font-medium text-[#342B40]">
                              {m.decision_what || m.invoice_number || "—"}
                            </span>
                          </div>
                          {m.decision_next && (
                            <p className="mt-1 text-xs text-[#9C3843] font-medium">
                              {m.decision_next}
                            </p>
                          )}
                        </li>
                      ))}
                    </ul>
                  )}
                </div>

                {/* Review-Required Items */}
                <div className="space-y-2">
                  <div className="flex items-center gap-2">
                    <span className="h-2 w-2 rounded-full bg-[#A56B26]" />
                    <h3 className="text-xs font-bold text-[#342B40]">
                      Review Required ({reviewMismatches.length})
                    </h3>
                  </div>
                  {reviewMismatches.length === 0 ? (
                    <p className="text-xs text-[#968BA2] italic">No review-required items.</p>
                  ) : (
                    <ul className="space-y-2">
                      {reviewMismatches.map((m, i) => (
                        <li
                          key={`review-${m.mismatch_type}-${i}`}
                          className="rounded-xl border border-[#FDE7B2] bg-[#FFF5DD]/40 px-3.5 py-2.5"
                        >
                          <div className="flex flex-wrap items-center gap-2">
                            <TypePill type={m.mismatch_type} />
                            <SeverityPill severity={m.mismatch_severity} />
                            <span className="text-xs font-medium text-[#342B40]">
                              {m.decision_what || m.invoice_number || "—"}
                            </span>
                          </div>
                          {m.decision_next && (
                            <p className="mt-1 text-xs text-[#97621C] font-medium">
                              {m.decision_next}
                            </p>
                          )}
                        </li>
                      ))}
                    </ul>
                  )}
                </div>
              </div>
            </div>
          )}
        </div>
      </div>

      {/* 5. Sticky Bottom Action Bar */}
      <div
        className={styles.footerBar}
        style={{ left: "var(--workspace-sidebar-offset, 252px)" }}
      >
        <div className={styles.footerInner}>
          <div className="flex min-w-0 items-start gap-2.5 rounded-xl border border-[#EEE8F4] bg-[#FAF9FC] px-3.5 py-2">
            <Check
              className="mt-0.5 h-3.5 w-3.5 shrink-0 text-[#78608F]"
              aria-hidden
            />
            <div className="min-w-0">
              <p className="text-xs font-bold text-[#342B40]">
                Checklist before filing
              </p>
              <p className="mt-0.5 text-[11px] leading-snug text-[#756184]">
                Review Required, Missing in GSTR-1, Extra in GSTR-1, and the
                GSTR-1 vs 3B tie-out before amending returns.
              </p>
            </div>
          </div>

          <div className="flex shrink-0 flex-wrap items-center gap-2">
            {onRunAgain && (
              <button
                type="button"
                className="rounded-[7px] border border-[#E5DCEE] bg-white px-4 py-2 text-xs font-semibold text-[#594C66] transition-colors hover:bg-[#FAF8FC] hover:border-[#D8CDE3] hover:text-[#342B40]"
                onClick={onRunAgain}
              >
                Run again
              </button>
            )}
            {filingHref && (
              <Link
                href={filingHref}
                className="rounded-[7px] border border-[#E5DCEE] bg-white px-4 py-2 text-xs font-semibold text-[#594C66] transition-colors hover:bg-[#FAF8FC] hover:border-[#D8CDE3] hover:text-[#342B40]"
              >
                File GSTR-1
              </Link>
            )}
            <button
              type="button"
              disabled={pdfBusy}
              className="rounded-[7px] bg-[#342B40] px-4 py-2 text-xs font-semibold text-white shadow-xs transition-colors hover:bg-[#251E2F] disabled:opacity-50"
              onClick={() => void handlePdf()}
            >
              Export PDF report
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}
