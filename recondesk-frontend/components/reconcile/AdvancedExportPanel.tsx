"use client";

import { ChevronDown, FileSpreadsheet, FileText, Loader2 } from "lucide-react";
import { useCallback, useMemo, useState } from "react";

import {
  csvDownloadBtnClass,
  filterDropdownClass,
  filterToolbarClass,
  sectionContainerClass,
} from "@/components/reconcile/ResultsUi";
import { downloadBlobAsFile } from "@/lib/download";

const API_URL = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

const STATUS_OPTIONS = [
  { value: "MATCHED", label: "Matched" },
  { value: "MISMATCHED", label: "Mismatched" },
  { value: "MISSING", label: "Missing" },
  { value: "ITC_AT_RISK", label: "ITC at Risk — Not in GSTR-2B" },
  { value: "DUPLICATE", label: "Duplicate" },
] as const;

type AdvancedExportPanelProps = {
  runId: string;
  authToken: string | null;
  clientName: string;
  period: string;
  /** When set, shown as a selectable client filter (multi-client views). */
  clientId?: string | null;
  /** Optional extra clients for multi-client views. */
  clients?: Array<{ id: string; name: string }>;
  onError?: (message: string) => void;
};

type PreviewResponse = {
  matched_row_count: number;
  count_by_status: Record<string, number>;
  count_by_itc_category: Record<string, number>;
  total_itc_at_risk: number;
  available_itc_categories: string[];
  client_id: string;
  client_name: string;
  period: string;
};

function toggleValue(list: string[], value: string): string[] {
  return list.includes(value) ? list.filter((v) => v !== value) : [...list, value];
}

function filenameFromDisposition(header: string | null, fallback: string): string {
  if (!header) return fallback;
  const m = /filename="?([^";]+)"?/i.exec(header);
  return m?.[1]?.trim() || fallback;
}

export function AdvancedExportPanel({
  runId,
  authToken,
  clientName,
  period,
  clientId,
  clients,
  onError,
}: AdvancedExportPanelProps) {
  const [open, setOpen] = useState(false);
  const [statuses, setStatuses] = useState<string[]>([]);
  const [selectedClients, setSelectedClients] = useState<string[]>([]);
  const [periodFilter, setPeriodFilter] = useState(period || "");
  const [itcCategories, setItcCategories] = useState<string[]>([]);
  const [availableItc, setAvailableItc] = useState<string[]>([]);
  const [previewCount, setPreviewCount] = useState<number | null>(null);
  const [previewLoading, setPreviewLoading] = useState(false);
  const [xlsxLoading, setXlsxLoading] = useState(false);
  const [pdfLoading, setPdfLoading] = useState(false);

  const clientOptions = useMemo(() => {
    if (clients && clients.length > 0) return clients;
    if (clientId) return [{ id: clientId, name: clientName || clientId }];
    return [];
  }, [clients, clientId, clientName]);

  const showClientFilter = clientOptions.length > 1;

  const buildBody = useCallback(
    (format: "preview" | "xlsx" | "pdf") => ({
      run_id: runId,
      format,
      filters: {
        status: statuses,
        client_id: showClientFilter ? selectedClients : clientId ? [clientId] : [],
        period: periodFilter.trim() || undefined,
        itc_category: itcCategories,
      },
    }),
    [
      runId,
      statuses,
      selectedClients,
      showClientFilter,
      clientId,
      periodFilter,
      itcCategories,
    ]
  );

  const postExport = useCallback(
    async (format: "preview" | "xlsx" | "pdf") => {
      if (!authToken || !runId) return null;
      const res = await fetch(`${API_URL}/api/export/advanced`, {
        method: "POST",
        headers: {
          Authorization: `Bearer ${authToken}`,
          "Content-Type": "application/json",
        },
        body: JSON.stringify(buildBody(format)),
      });
      if (!res.ok) {
        let detail = `Export failed (${res.status})`;
        try {
          const j = (await res.json()) as { detail?: string };
          if (j?.detail) detail = String(j.detail);
        } catch {
          /* ignore */
        }
        throw new Error(detail);
      }
      return res;
    },
    [authToken, runId, buildBody]
  );

  const applyFiltersPreview = useCallback(async () => {
    if (!authToken || !runId) return;
    setPreviewLoading(true);
    try {
      const res = await postExport("preview");
      if (!res) return;
      const data = (await res.json()) as PreviewResponse;
      setPreviewCount(data.matched_row_count);
      if (Array.isArray(data.available_itc_categories)) {
        setAvailableItc(data.available_itc_categories);
      }
    } catch (e) {
      setPreviewCount(null);
      onError?.(e instanceof Error ? e.message : "Failed to preview filters");
    } finally {
      setPreviewLoading(false);
    }
  }, [authToken, runId, postExport, onError]);

  const downloadFile = useCallback(
    async (format: "xlsx" | "pdf") => {
      if (!authToken || !runId) return;
      const setLoading = format === "xlsx" ? setXlsxLoading : setPdfLoading;
      setLoading(true);
      try {
        const res = await postExport(format);
        if (!res) return;
        const blob = await res.blob();
        const fallback =
          format === "xlsx"
            ? `ReconDesk_Advanced_${period || "export"}.xlsx`
            : `ReconDesk_Advanced_${period || "export"}.pdf`;
        const name = filenameFromDisposition(
          res.headers.get("Content-Disposition"),
          fallback
        );
        downloadBlobAsFile(blob, name);
      } catch (e) {
        onError?.(
          e instanceof Error
            ? e.message
            : `Failed to export ${format === "xlsx" ? "Excel" : "PDF"}`
        );
      } finally {
        setLoading(false);
      }
    },
    [authToken, runId, postExport, period, onError]
  );

  return (
    <section className={`${sectionContainerClass} !mb-0`} aria-label="Advanced Export">
      <button
        type="button"
        className="flex w-full items-center justify-between gap-3 text-left"
        onClick={() => setOpen((v) => !v)}
        aria-expanded={open}
      >
        <div>
          <h2 className="text-[15px] font-semibold tracking-tight text-[var(--ink)]">
            Advanced Export
          </h2>
          <p className="mt-0.5 text-[12px] text-gray-500">
            Filter by status, period, and ITC eligibility, then export Excel or PDF
          </p>
        </div>
        <ChevronDown
          className={`h-4 w-4 shrink-0 text-gray-400 transition-transform ${
            open ? "rotate-180" : ""
          }`}
        />
      </button>

      {open && (
        <div className={`${filterToolbarClass} mt-4 border-t border-[#F0F0F0] pt-4`}>
          <div className="space-y-3">
            <div>
              <p className="mb-1.5 text-[12px] font-medium text-gray-600">Status</p>
              <div className="flex flex-wrap gap-2">
                {STATUS_OPTIONS.map((opt) => {
                  const active = statuses.includes(opt.value);
                  return (
                    <button
                      key={opt.value}
                      type="button"
                      onClick={() => {
                        setStatuses((prev) => toggleValue(prev, opt.value));
                        setPreviewCount(null);
                      }}
                      className={`inline-flex h-8 items-center rounded-full px-3 text-[12px] font-medium transition-colors ${
                        active
                          ? "bg-[var(--ink)] text-white"
                          : "bg-[#F5F5F6] text-gray-600 hover:bg-gray-200/70"
                      }`}
                    >
                      {opt.label}
                    </button>
                  );
                })}
              </div>
              <p className="mt-1 text-[11px] text-gray-400">
                Leave empty to include all statuses
              </p>
            </div>

            {showClientFilter && (
              <div>
                <p className="mb-1.5 text-[12px] font-medium text-gray-600">Client</p>
                <div className="flex flex-wrap gap-2">
                  {clientOptions.map((c) => {
                    const active = selectedClients.includes(c.id);
                    return (
                      <button
                        key={c.id}
                        type="button"
                        onClick={() => {
                          setSelectedClients((prev) => toggleValue(prev, c.id));
                          setPreviewCount(null);
                        }}
                        className={`inline-flex h-8 items-center rounded-full px-3 text-[12px] font-medium transition-colors ${
                          active
                            ? "bg-[var(--ink)] text-white"
                            : "bg-[#F5F5F6] text-gray-600 hover:bg-gray-200/70"
                        }`}
                      >
                        {c.name}
                      </button>
                    );
                  })}
                </div>
              </div>
            )}

            <div className="flex flex-wrap items-end gap-3">
              <label className="block">
                <span className="mb-1.5 block text-[12px] font-medium text-gray-600">
                  Period
                </span>
                <input
                  type="text"
                  value={periodFilter}
                  onChange={(e) => {
                    setPeriodFilter(e.target.value);
                    setPreviewCount(null);
                  }}
                  placeholder={period || "YYYY-MM"}
                  className={`${filterDropdownClass} w-[140px]`}
                />
              </label>

              <label className="block min-w-[180px] flex-1">
                <span className="mb-1.5 block text-[12px] font-medium text-gray-600">
                  ITC eligibility category
                </span>
                <select
                  multiple
                  value={itcCategories}
                  onChange={(e) => {
                    const selected = Array.from(e.target.selectedOptions).map(
                      (o) => o.value
                    );
                    setItcCategories(selected);
                    setPreviewCount(null);
                  }}
                  className={`${filterDropdownClass} h-auto min-h-[72px] w-full max-w-md rounded-2xl py-1.5`}
                >
                  {(availableItc.length > 0
                    ? availableItc
                    : ["Yes", "No", "Eligible", "Ineligible", "Blocked", "(blank)"]
                  ).map((cat) => (
                    <option key={cat} value={cat}>
                      {cat}
                    </option>
                  ))}
                </select>
                <span className="mt-1 block text-[11px] text-gray-400">
                  Hold Ctrl/Cmd to multi-select. Apply Filters loads categories from this
                  run.
                </span>
              </label>
            </div>
          </div>

          <div className="mt-4 flex flex-wrap items-center gap-2">
            <button
              type="button"
              disabled={previewLoading || !authToken}
              onClick={() => void applyFiltersPreview()}
              className={csvDownloadBtnClass}
            >
              {previewLoading ? (
                <Loader2 className="h-4 w-4 animate-spin text-gray-400" />
              ) : null}
              Apply Filters
            </button>

            {previewCount !== null && (
              <span className="text-[13px] text-gray-600">
                {previewCount.toLocaleString("en-IN")} row
                {previewCount === 1 ? "" : "s"} match
              </span>
            )}

            <div className="ml-auto flex flex-wrap items-center gap-2">
              <button
                type="button"
                disabled={xlsxLoading || !authToken}
                onClick={() => void downloadFile("xlsx")}
                className={csvDownloadBtnClass}
              >
                {xlsxLoading ? (
                  <Loader2 className="h-4 w-4 animate-spin text-gray-400" />
                ) : (
                  <FileSpreadsheet className="h-4 w-4 text-gray-500" />
                )}
                Export to Excel
              </button>
              <button
                type="button"
                disabled={pdfLoading || !authToken}
                onClick={() => void downloadFile("pdf")}
                className={csvDownloadBtnClass}
              >
                {pdfLoading ? (
                  <Loader2 className="h-4 w-4 animate-spin text-gray-400" />
                ) : (
                  <FileText className="h-4 w-4 text-gray-500" />
                )}
                Export to PDF
              </button>
            </div>
          </div>
        </div>
      )}
    </section>
  );
}
