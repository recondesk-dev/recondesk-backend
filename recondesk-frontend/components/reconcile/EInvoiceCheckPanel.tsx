"use client";

import { useState, useCallback, useMemo } from "react";
import { Upload, FileSpreadsheet, AlertCircle, CheckCircle, RefreshCw, Info, ChevronDown } from "lucide-react";
import { apiFetch } from "@/lib/api";
import { formatINR } from "@/lib/format";
import {
  sectionContainerClass,
  filterToolbarClass,
  filterRowClass,
  filterInputClass,
  tableWrapClass,
  matchedTableClass,
  matchedThInvoice,
  matchedThDate,
  matchedThGstin,
  matchedThAmount,
  matchedThNotes,
  matchedTdInvoice,
  matchedTdDate,
  matchedTdGstin,
  matchedTdAmount,
  matchedTdNotes,
  tableRowClass,
  EmptyTableState,
} from "./ResultsUi";

type CategoryFilter = "ALL" | "MATCHED" | "IRN_MISSING" | "IRN_CANCELLED" | "EXTRA_IRN" | "VALUE_MISMATCH";

interface EInvoiceResultItem {
  id?: string;
  invoice_number: string;
  invoice_date?: string | null;
  gstin?: string;
  category: "MATCHED" | "IRN_MISSING" | "IRN_CANCELLED" | "EXTRA_IRN" | "VALUE_MISMATCH" | string;
  book_value: number;
  einvoice_value: number;
  value_difference?: number;
  irn?: string | null;
  irn_status?: string | null;
  ack_number?: string | null;
  ack_date?: string | null;
  decision_what?: string | null;
  decision_why?: string | null;
  decision_next?: string | null;
  decision_rule?: string | null;
}

interface EInvoiceSummary {
  total_records: number;
  matched_count: number;
  irn_missing_count: number;
  irn_cancelled_count: number;
  extra_irn_count: number;
  value_mismatch_count: number;
  matched_value?: number;
  irn_missing_value?: number;
  irn_cancelled_value?: number;
  extra_irn_value?: number;
  value_mismatch_difference?: number;
}

export function EInvoiceCheckPanel({
  runId,
  clientGstinId,
  period,
  authToken,
}: {
  runId?: string;
  clientGstinId?: string;
  period?: string;
  authToken?: string;
}) {
  const [file, setFile] = useState<File | null>(null);
  const [isDragOver, setIsDragOver] = useState(false);
  const [uploading, setUploading] = useState(false);
  const [running, setRunning] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [results, setResults] = useState<EInvoiceResultItem[] | null>(null);
  const [summary, setSummary] = useState<EInvoiceSummary | null>(null);
  const [activeCategory, setActiveCategory] = useState<CategoryFilter>("ALL");
  const [searchQuery, setSearchQuery] = useState("");

  // Handle Drag & Drop
  const handleDragOver = useCallback((e: React.DragEvent) => {
    e.preventDefault();
    setIsDragOver(true);
  }, []);

  const handleDragLeave = useCallback((e: React.DragEvent) => {
    e.preventDefault();
    setIsDragOver(false);
  }, []);

  const handleDrop = useCallback((e: React.DragEvent) => {
    e.preventDefault();
    setIsDragOver(false);
    if (e.dataTransfer.files && e.dataTransfer.files[0]) {
      const selected = e.dataTransfer.files[0];
      const name = selected.name.toLowerCase();
      if (name.endsWith(".xlsx") || name.endsWith(".xls") || name.endsWith(".csv")) {
        setFile(selected);
        setError(null);
      } else {
        setError("Only .xlsx, .xls, and .csv files are supported.");
      }
    }
  }, []);

  const handleFileChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    if (e.target.files && e.target.files[0]) {
      setFile(e.target.files[0]);
      setError(null);
    }
  };

  const handleRunRecon = async () => {
    if (!file && !runId) {
      setError("Please select an E-Invoice report file (.xlsx / .csv).");
      return;
    }
    setRunning(true);
    setError(null);

    try {
      const formData = new FormData();
      if (file) {
        formData.append("file", file);
      }
      if (clientGstinId) {
        formData.append("client_id", clientGstinId);
      }
      if (period) {
        formData.append("period", period);
      }

      const res = await apiFetch<any>("/api/einvoice-recon/run", {
        method: "POST",
        body: formData,
      });

      if (res && res.results) {
        setResults(res.results);
        setSummary(res.summary);
      } else {
        setError("No reconciliation results returned from server.");
      }
    } catch (err: any) {
      setError(err?.message || "Failed to run E-Invoice reconciliation.");
    } finally {
      setRunning(false);
    }
  };

  const filteredResults = useMemo(() => {
    if (!results) return [];
    return results.filter((item) => {
      if (activeCategory !== "ALL" && item.category !== activeCategory) {
        return false;
      }
      if (searchQuery.trim()) {
        const q = searchQuery.toLowerCase();
        const invMatch = item.invoice_number?.toLowerCase().includes(q);
        const gstinMatch = item.gstin?.toLowerCase().includes(q);
        const irnMatch = item.irn?.toLowerCase().includes(q);
        return invMatch || gstinMatch || irnMatch;
      }
      return true;
    });
  }, [results, activeCategory, searchQuery]);

  const getCategoryBadgeClass = (category: string) => {
    switch (category) {
      case "MATCHED":
        return "bg-emerald-50 text-emerald-700 border-emerald-200";
      case "IRN_MISSING":
        return "bg-amber-50 text-amber-700 border-amber-200";
      case "IRN_CANCELLED":
        return "bg-rose-50 text-rose-700 border-rose-200";
      case "EXTRA_IRN":
        return "bg-blue-50 text-blue-700 border-blue-200";
      case "VALUE_MISMATCH":
        return "bg-purple-50 text-purple-700 border-purple-200";
      default:
        return "bg-gray-50 text-gray-700 border-gray-200";
    }
  };

  return (
    <div className={sectionContainerClass}>
      <div className="mb-6 flex flex-col gap-2 sm:flex-row sm:items-center sm:justify-between">
        <div>
          <h2 className="text-[16px] font-semibold tracking-tight text-gray-900">
            Books-to-E-Invoice Reconciliation
          </h2>
          <p className="text-[12px] text-gray-500">
            Cross-verify Purchase/Sales Register books against IRP E-Invoice portal exports.
          </p>
        </div>
      </div>

      {/* Upload UI Box */}
      <div
        onDragOver={handleDragOver}
        onDragLeave={handleDragLeave}
        onDrop={handleDrop}
        className={`mb-6 flex flex-col items-center justify-center rounded-xl border-2 border-dashed p-6 text-center transition-colors ${
          isDragOver
            ? "border-[var(--ink)] bg-emerald-50/30"
            : file
            ? "border-emerald-300 bg-emerald-50/10"
            : "border-gray-200 bg-gray-50/50 hover:bg-gray-50"
        }`}
      >
        <div className="mb-3 flex h-10 w-10 items-center justify-center rounded-full bg-white shadow-sm ring-1 ring-gray-900/5">
          {file ? (
            <FileSpreadsheet className="h-5 w-5 text-emerald-600" />
          ) : (
            <Upload className="h-5 w-5 text-gray-400" />
          )}
        </div>
        {file ? (
          <div className="mb-3">
            <span className="text-[13px] font-semibold text-gray-900">{file.name}</span>
            <span className="ml-2 text-[11px] text-gray-500">
              ({(file.size / 1024).toFixed(1)} KB)
            </span>
          </div>
        ) : (
          <div className="mb-3">
            <label
              htmlFor="einvoice-file-upload"
              className="cursor-pointer text-[13px] font-medium text-[var(--ink)] hover:underline"
            >
              Upload E-Invoice Report (.xlsx / .csv)
            </label>
            <input
              id="einvoice-file-upload"
              type="file"
              accept=".xlsx,.xls,.csv"
              className="sr-only"
              onChange={handleFileChange}
            />
            <p className="text-[11px] text-gray-400">or drag and drop export file here</p>
          </div>
        )}

        <div className="flex gap-2">
          {file && (
            <button
              type="button"
              onClick={() => setFile(null)}
              className="rounded-lg border border-gray-200 bg-white px-3 py-1.5 text-[12px] font-medium text-gray-600 hover:bg-gray-50"
            >
              Clear File
            </button>
          )}
          <button
            type="button"
            disabled={running || !file}
            onClick={handleRunRecon}
            className="inline-flex items-center gap-1.5 rounded-lg bg-[var(--ink)] px-4 py-1.5 text-[12px] font-semibold text-white shadow-sm transition-opacity hover:opacity-90 disabled:opacity-50"
          >
            {running ? (
              <>
                <RefreshCw className="h-3.5 w-3.5 animate-spin" />
                Matching Records...
              </>
            ) : (
              <>
                <CheckCircle className="h-3.5 w-3.5" />
                Run E-Invoice Check
              </>
            )}
          </button>
        </div>
      </div>

      {error && (
        <div className="mb-6 flex items-center gap-2 rounded-lg border border-rose-200 bg-rose-50 px-4 py-3 text-[13px] text-rose-700">
          <AlertCircle className="h-4 w-4 shrink-0" />
          <span>{error}</span>
        </div>
      )}

      {/* KPI Cards */}
      {summary && (
        <div className="mb-6 grid grid-cols-2 gap-3 sm:grid-cols-5">
          <div className="rounded-xl border border-emerald-200 bg-emerald-50/40 p-3.5">
            <span className="text-[11px] font-medium text-emerald-800">Matched</span>
            <div className="mt-1 text-lg font-bold text-emerald-900">
              {summary.matched_count}
            </div>
            <span className="text-[11px] text-emerald-700">
              {formatINR(summary.matched_value || 0)}
            </span>
          </div>

          <div className="rounded-xl border border-amber-200 bg-amber-50/40 p-3.5">
            <span className="text-[11px] font-medium text-amber-800">IRN Missing</span>
            <div className="mt-1 text-lg font-bold text-amber-900">
              {summary.irn_missing_count}
            </div>
            <span className="text-[11px] text-amber-700">
              {formatINR(summary.irn_missing_value || 0)}
            </span>
          </div>

          <div className="rounded-xl border border-rose-200 bg-rose-50/40 p-3.5">
            <span className="text-[11px] font-medium text-rose-800">IRN Cancelled</span>
            <div className="mt-1 text-lg font-bold text-rose-900">
              {summary.irn_cancelled_count}
            </div>
            <span className="text-[11px] text-rose-700">
              {formatINR(summary.irn_cancelled_value || 0)}
            </span>
          </div>

          <div className="rounded-xl border border-blue-200 bg-blue-50/40 p-3.5">
            <span className="text-[11px] font-medium text-blue-800">Extra IRN</span>
            <div className="mt-1 text-lg font-bold text-blue-900">
              {summary.extra_irn_count}
            </div>
            <span className="text-[11px] text-blue-700">
              {formatINR(summary.extra_irn_value || 0)}
            </span>
          </div>

          <div className="rounded-xl border border-purple-200 bg-purple-50/40 p-3.5">
            <span className="text-[11px] font-medium text-purple-800">Value Mismatch</span>
            <div className="mt-1 text-lg font-bold text-purple-900">
              {summary.value_mismatch_count}
            </div>
            <span className="text-[11px] text-purple-700">
              Diff: {formatINR(summary.value_mismatch_difference || 0)}
            </span>
          </div>
        </div>
      )}

      {/* Category Filter Chips & Search Toolbar */}
      {results && (
        <>
          <div className="mb-4 flex flex-wrap items-center justify-between gap-3">
            <div className="flex flex-wrap gap-1.5">
              {(
                [
                  { id: "ALL", label: `All (${results.length})` },
                  { id: "MATCHED", label: `Matched (${summary?.matched_count || 0})` },
                  { id: "IRN_MISSING", label: `IRN Missing (${summary?.irn_missing_count || 0})` },
                  { id: "IRN_CANCELLED", label: `IRN Cancelled (${summary?.irn_cancelled_count || 0})` },
                  { id: "EXTRA_IRN", label: `Extra IRN (${summary?.extra_irn_count || 0})` },
                  { id: "VALUE_MISMATCH", label: `Value Mismatch (${summary?.value_mismatch_count || 0})` },
                ] as const
              ).map(({ id, label }) => (
                <button
                  key={id}
                  type="button"
                  onClick={() => setActiveCategory(id)}
                  className={
                    activeCategory === id
                      ? "rounded-full bg-[var(--ink)] px-3 py-1 text-[12px] font-semibold text-white shadow-sm"
                      : "rounded-full bg-white px-3 py-1 text-[12px] font-medium text-gray-600 shadow-[var(--shadow-soft)] hover:text-gray-900"
                  }
                >
                  {label}
                </button>
              ))}
            </div>

            <div>
              <input
                type="text"
                placeholder="Search invoice, GSTIN, IRN..."
                value={searchQuery}
                onChange={(e) => setSearchQuery(e.target.value)}
                className={filterInputClass}
              />
            </div>
          </div>

          {/* Results Table */}
          <div className={tableWrapClass}>
            <table className={matchedTableClass}>
              <thead>
                <tr>
                  <th className={matchedThInvoice}>Invoice No</th>
                  <th className={matchedThDate}>Date</th>
                  <th className={matchedThGstin}>GSTIN</th>
                  <th className="px-3 py-2 text-left text-[11px] font-semibold uppercase tracking-wider text-gray-500">
                    Category
                  </th>
                  <th className={matchedThAmount}>Book Value</th>
                  <th className={matchedThAmount}>E-Invoice Value</th>
                  <th className="px-3 py-2 text-left text-[11px] font-semibold uppercase tracking-wider text-gray-500">
                    IRN / Status
                  </th>
                  <th className={matchedThNotes}>Decision & Guidance</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-gray-100 bg-white">
                {filteredResults.length === 0 ? (
                  <tr>
                    <td colSpan={8}>
                      <EmptyTableState
                        title="No records found"
                        description="No matching records found for selected category or filter."
                      />
                    </td>
                  </tr>
                ) : (
                  filteredResults.map((item, idx) => (
                    <tr key={item.id || idx} className={tableRowClass}>
                      <td className={matchedTdInvoice}>
                        <span className="font-semibold text-gray-900">{item.invoice_number}</span>
                      </td>
                      <td className={matchedTdDate}>{item.invoice_date || "—"}</td>
                      <td className={matchedTdGstin}>{item.gstin || "—"}</td>
                      <td className="px-3 py-2 whitespace-nowrap">
                        <span
                          className={`inline-flex rounded-full border px-2 py-0.5 text-[11px] font-semibold ${getCategoryBadgeClass(
                            item.category
                          )}`}
                        >
                          {item.category.replace("_", " ")}
                        </span>
                      </td>
                      <td className={matchedTdAmount}>{formatINR(item.book_value)}</td>
                      <td className={matchedTdAmount}>{formatINR(item.einvoice_value)}</td>
                      <td className="px-3 py-2 text-[11px]">
                        {item.irn ? (
                          <div>
                            <span className="font-mono text-gray-800" title={item.irn}>
                              {item.irn.slice(0, 10)}...{item.irn.slice(-6)}
                            </span>
                            <span
                              className={`ml-1.5 font-medium ${
                                item.irn_status === "Cancelled"
                                  ? "text-rose-600"
                                  : "text-emerald-600"
                              }`}
                            >
                              ({item.irn_status || "Active"})
                            </span>
                          </div>
                        ) : (
                          <span className="text-gray-400">None</span>
                        )}
                      </td>
                      <td className={matchedTdNotes}>
                        {item.decision_what ? (
                          <div className="space-y-1 leading-tight">
                            <div className="font-semibold text-gray-900">{item.decision_what}</div>
                            <div className="text-gray-500">{item.decision_why}</div>
                            {item.decision_next && (
                              <div className="font-medium text-emerald-700">
                                Next: {item.decision_next}
                              </div>
                            )}
                          </div>
                        ) : (
                          <span className="text-gray-400">—</span>
                        )}
                      </td>
                    </tr>
                  ))
                )}
              </tbody>
            </table>
          </div>
        </>
      )}
    </div>
  );
}
