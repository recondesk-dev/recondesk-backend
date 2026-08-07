"use client";

import { useState, useCallback, useMemo, useEffect } from "react";
import { Upload, FileSpreadsheet, AlertCircle, CheckCircle, RefreshCw, Info, Lock, Check, X, ShieldAlert, Loader2 } from "lucide-react";
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
  verification_source?: string | null;
  verified_at?: string | null;
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

  const [hasCredentials, setHasCredentials] = useState<boolean | null>(null);
  const [credUsername, setCredUsername] = useState("");
  const [credPassword, setCredPassword] = useState("");
  const [savingCreds, setSavingCreds] = useState(false);
  const [credError, setCredError] = useState<string | null>(null);
  const [credSuccess, setCredSuccess] = useState<string | null>(null);
  const [showCredForm, setShowCredForm] = useState(false);

  const [verifyingId, setVerifyingId] = useState<string | null>(null);
  const [batchVerifying, setBatchVerifying] = useState(false);

  useEffect(() => {
    if (clientGstinId) {
      apiFetch<any>(`/api/einvoice-recon/credentials/${clientGstinId}`)
        .then((res) => {
          setHasCredentials(res?.has_credentials ?? false);
          if (res?.username) {
            setCredUsername(res.username);
          }
        })
        .catch(() => setHasCredentials(false));
    }
  }, [clientGstinId]);

  const handleSaveCredentials = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!clientGstinId || !credUsername || !credPassword) return;
    setSavingCreds(true);
    setCredError(null);
    setCredSuccess(null);

    try {
      const res = await apiFetch<any>(`/api/einvoice-recon/credentials/${clientGstinId}`, {
        method: "POST",
        body: JSON.stringify({ username: credUsername, password: credPassword }),
      });
      if (res && res.has_credentials) {
        setHasCredentials(true);
        setCredSuccess("e-Invoice portal credentials saved securely.");
        setCredPassword("");
        setShowCredForm(false);
      }
    } catch (err: any) {
      setCredError(err?.message || "Failed to save credentials.");
    } finally {
      setSavingCreds(false);
    }
  };

  const handleVerifySingle = async (resultId: string) => {
    setVerifyingId(resultId);
    setError(null);
    try {
      const updated = await apiFetch<any>(`/api/einvoice-recon/results/${resultId}/verify`, {
        method: "POST",
      });
      if (updated && results) {
        setResults((prev) =>
          (prev || []).map((row) => (row.id === resultId ? { ...row, ...Object(updated) } : row))
        );
        if (updated.category === "MATCHED") {
          setSummary((prev) =>
            prev
              ? {
                  ...prev,
                  matched_count: prev.matched_count + 1,
                  irn_missing_count: Math.max(0, prev.irn_missing_count - 1),
                }
              : prev
          );
        }
      }
    } catch (err: any) {
      setError(err?.message || "IRP live verification failed.");
    } finally {
      setVerifyingId(null);
    }
  };

  const handleVerifyBatch = async () => {
    if (!results) return;
    const missingRows = results.filter(
      (r) => r.category === "IRN_MISSING" && r.verification_source !== "irp_verified_missing" && r.id
    );
    if (missingRows.length === 0) return;

    setBatchVerifying(true);
    setError(null);

    try {
      const res = await apiFetch<any>("/api/einvoice-recon/results/batch-verify", {
        method: "POST",
        body: JSON.stringify({ result_ids: missingRows.map((r) => r.id!) }),
      });
      if (res && res.results) {
        const resultMap = new Map(res.results.map((r: any) => [r.id, r]));
        setResults((prev) =>
          (prev || []).map((row) => {
            if (row.id && resultMap.has(row.id)) {
              return { ...row, ...Object(resultMap.get(row.id)) };
            }
            return row;
          })
        );
        if (res.matched_upgrades > 0) {
          setSummary((prev) =>
            prev
              ? {
                  ...prev,
                  matched_count: prev.matched_count + res.matched_upgrades,
                  irn_missing_count: Math.max(0, prev.irn_missing_count - res.matched_upgrades),
                }
              : prev
          );
        }
      }
    } catch (err: any) {
      setError(err?.message || "Batch verification failed.");
    } finally {
      setBatchVerifying(false);
    }
  };

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

  const unverifiedMissingCount = useMemo(() => {
    if (!results) return 0;
    return results.filter(
      (r) => r.category === "IRN_MISSING" && r.verification_source !== "irp_verified_missing" && r.id
    ).length;
  }, [results]);

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
      <div className="mb-6 flex flex-col gap-4 sm:flex-row sm:items-center sm:justify-between">
        <div>
          <h2 className="text-[16px] font-semibold tracking-tight text-gray-900">
            Books-to-E-Invoice Reconciliation
          </h2>
          <p className="text-[12px] text-gray-500">
            Cross-verify Purchase/Sales Register books against IRP E-Invoice portal exports & live API lookups.
          </p>
        </div>

        {clientGstinId && (
          <div>
            {hasCredentials ? (
              <button
                type="button"
                onClick={() => setShowCredForm((v) => !v)}
                className="inline-flex items-center gap-1.5 rounded-full border border-emerald-200 bg-emerald-50 px-3 py-1.5 text-[12px] font-semibold text-emerald-800 shadow-sm hover:bg-emerald-100"
              >
                <Lock className="h-3.5 w-3.5 text-emerald-600" />
                <span>IRP Credentials Set ({credUsername || "Configured"})</span>
              </button>
            ) : (
              <button
                type="button"
                onClick={() => setShowCredForm((v) => !v)}
                className="inline-flex items-center gap-1.5 rounded-full border border-amber-200 bg-amber-50 px-3 py-1.5 text-[12px] font-semibold text-amber-800 shadow-sm hover:bg-amber-100"
              >
                <ShieldAlert className="h-3.5 w-3.5 text-amber-600" />
                <span>Add IRP Credentials for Live Lookup</span>
              </button>
            )}
          </div>
        )}
      </div>

      {showCredForm && (
        <div className="mb-6 rounded-xl border border-gray-200 bg-gray-50/70 p-4">
          <div className="mb-2 flex items-center justify-between">
            <h3 className="text-[13px] font-semibold text-gray-900">
              Configure e-Invoice Portal Credentials
            </h3>
            <button
              type="button"
              onClick={() => setShowCredForm(false)}
              className="text-gray-400 hover:text-gray-600"
            >
              <X className="h-4 w-4" />
            </button>
          </div>
          <p className="mb-3 text-[12px] text-gray-600">
            Enter the client&apos;s e-Invoice portal (einvoice1.gst.gov.in / Sandbox) API username and password to enable live per-invoice verification against IRP. Passwords are encrypted at rest using AES-256.
          </p>

          <form onSubmit={handleSaveCredentials} className="flex flex-wrap items-end gap-3">
            <div>
              <label className="block text-[11px] font-medium text-gray-700">Username</label>
              <input
                type="text"
                required
                value={credUsername}
                onChange={(e) => setCredUsername(e.target.value)}
                placeholder="e-Invoice API username"
                className="mt-1 block h-9 rounded-lg border border-gray-300 px-3 text-[13px] shadow-sm focus:border-[var(--ink)] focus:outline-none"
              />
            </div>
            <div>
              <label className="block text-[11px] font-medium text-gray-700">Password</label>
              <input
                type="password"
                required
                value={credPassword}
                onChange={(e) => setCredPassword(e.target.value)}
                placeholder="••••••••••••"
                className="mt-1 block h-9 rounded-lg border border-gray-300 px-3 text-[13px] shadow-sm focus:border-[var(--ink)] focus:outline-none"
              />
            </div>
            <button
              type="submit"
              disabled={savingCreds}
              className="inline-flex h-9 items-center justify-center gap-1.5 rounded-lg bg-[var(--ink)] px-4 text-[13px] font-semibold text-white shadow-sm hover:opacity-90 disabled:opacity-50"
            >
              {savingCreds ? <Loader2 className="h-4 w-4 animate-spin" /> : <Check className="h-4 w-4" />}
              Save Credentials
            </button>
          </form>

          {credError && <p className="mt-2 text-[12px] font-medium text-rose-600">{credError}</p>}
          {credSuccess && <p className="mt-2 text-[12px] font-medium text-emerald-600">{credSuccess}</p>}
        </div>
      )}

      {hasCredentials === false && !showCredForm && (
        <div className="mb-6 flex items-center justify-between rounded-xl border border-amber-200 bg-amber-50/60 p-3.5 text-[13px]">
          <div className="flex items-center gap-2.5 text-amber-900">
            <Info className="h-4 w-4 shrink-0 text-amber-600" />
            <span>Add IRP credentials to enable live verification for missing invoices directly against the portal.</span>
          </div>
          <button
            type="button"
            onClick={() => setShowCredForm(true)}
            className="rounded-lg bg-amber-800 px-3 py-1.5 text-[12px] font-semibold text-white hover:bg-amber-900"
          >
            Configure Credentials
          </button>
        </div>
      )}

      <div className="mb-6 rounded-xl border border-dashed border-gray-300 bg-gray-50/50 p-6 transition-colors">
        <div
          onDragOver={handleDragOver}
          onDragLeave={handleDragLeave}
          onDrop={handleDrop}
          className={`flex flex-col items-center justify-center text-center ${
            isDragOver ? "border-emerald-500 bg-emerald-50/30" : ""
          }`}
        >
          <div className="mb-2 flex h-10 w-10 items-center justify-center rounded-full bg-emerald-50 text-emerald-600">
            <FileSpreadsheet className="h-5 w-5" />
          </div>
          <p className="text-[13px] font-semibold text-gray-900">
            Upload E-Invoice Portal Export Report (.xlsx / .csv)
          </p>
          <p className="mt-1 text-[12px] text-gray-500">
            Drag &amp; drop file here, or click to select from computer
          </p>

          <input
            type="file"
            id="einvoice-file-input"
            accept=".xlsx,.xls,.csv"
            onChange={handleFileChange}
            className="hidden"
          />

          <div className="mt-4 flex items-center gap-3">
            <label
              htmlFor="einvoice-file-input"
              className="inline-flex cursor-pointer items-center gap-2 rounded-lg border border-gray-300 bg-white px-4 py-2 text-[13px] font-medium text-gray-700 shadow-sm hover:bg-gray-50"
            >
              <Upload className="h-4 w-4 text-gray-500" />
              <span>{file ? file.name : "Browse File"}</span>
            </label>

            <button
              type="button"
              onClick={handleRunRecon}
              disabled={running || (!file && !runId)}
              className="inline-flex items-center gap-2 rounded-lg bg-[var(--ink)] px-5 py-2 text-[13px] font-semibold text-white shadow-sm transition-opacity hover:opacity-90 disabled:cursor-not-allowed disabled:opacity-50"
            >
              {running ? (
                <>
                  <RefreshCw className="h-4 w-4 animate-spin" />
                  <span>Reconciling...</span>
                </>
              ) : (
                <span>Run E-Invoice Check</span>
              )}
            </button>
          </div>
        </div>
      </div>

      {error && (
        <div className="mb-6 flex items-center gap-2 rounded-lg border border-rose-200 bg-rose-50 p-3.5 text-[13px] font-medium text-rose-700">
          <AlertCircle className="h-4 w-4 shrink-0" />
          <span>{error}</span>
        </div>
      )}

      {summary && (
        <div className="mb-6 grid grid-cols-2 gap-3 sm:grid-cols-5">
          <div className="rounded-xl border border-emerald-200 bg-emerald-50/40 p-3.5">
            <span className="text-[11px] font-medium text-emerald-800">Matched IRN</span>
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

            <div className="flex items-center gap-3">
              {unverifiedMissingCount > 0 && hasCredentials && (
                <button
                  type="button"
                  onClick={handleVerifyBatch}
                  disabled={batchVerifying}
                  className="inline-flex items-center gap-1.5 rounded-lg border border-amber-300 bg-amber-50 px-3 py-1.5 text-[12px] font-semibold text-amber-900 shadow-sm hover:bg-amber-100 disabled:opacity-50"
                >
                  {batchVerifying ? (
                    <>
                      <Loader2 className="h-3.5 w-3.5 animate-spin text-amber-700" />
                      <span>Verifying on IRP...</span>
                    </>
                  ) : (
                    <>
                      <RefreshCw className="h-3.5 w-3.5 text-amber-700" />
                      <span>Verify All Missing ({unverifiedMissingCount})</span>
                    </>
                  )}
                </button>
              )}

              <input
                type="text"
                placeholder="Search invoice, GSTIN, IRN..."
                value={searchQuery}
                onChange={(e) => setSearchQuery(e.target.value)}
                className={filterInputClass}
              />
            </div>
          </div>

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
                  <th className={matchedThNotes}>Decision &amp; Guidance</th>
                  <th className="px-3 py-2 text-center text-[11px] font-semibold uppercase tracking-wider text-gray-500">
                    Action
                  </th>
                </tr>
              </thead>
              <tbody className="divide-y divide-gray-100 bg-white">
                {filteredResults.length === 0 ? (
                  <tr>
                    <td colSpan={9}>
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

                      <td className="px-3 py-2 text-center whitespace-nowrap text-[11px]">
                        {item.verification_source === "irp_live_lookup" ? (
                          <span className="inline-flex items-center gap-1 rounded-full border border-emerald-300 bg-emerald-50 px-2.5 py-0.5 text-[11px] font-semibold text-emerald-800">
                            <Check className="h-3 w-3 text-emerald-600" />
                            <span>Verified via IRP</span>
                          </span>
                        ) : item.verification_source === "irp_verified_missing" ? (
                          <span className="inline-flex items-center gap-1 rounded-full border border-amber-300 bg-amber-50 px-2.5 py-0.5 text-[11px] font-semibold text-amber-900">
                            <X className="h-3 w-3 text-amber-600" />
                            <span>Confirmed missing from IRP</span>
                          </span>
                        ) : item.category === "IRN_MISSING" && item.id ? (
                          hasCredentials ? (
                            <button
                              type="button"
                              onClick={() => handleVerifySingle(item.id!)}
                              disabled={verifyingId === item.id || batchVerifying}
                              className="inline-flex items-center gap-1 rounded-md border border-amber-300 bg-amber-50 px-2.5 py-1 text-[11px] font-semibold text-amber-900 hover:bg-amber-100 disabled:opacity-50"
                            >
                              {verifyingId === item.id ? (
                                <>
                                  <Loader2 className="h-3 w-3 animate-spin text-amber-700" />
                                  <span>Verifying...</span>
                                </>
                              ) : (
                                <span>Verify on IRP</span>
                              )}
                            </button>
                          ) : (
                            <button
                              type="button"
                              onClick={() => setShowCredForm(true)}
                              className="text-[11px] font-medium text-amber-700 underline hover:text-amber-900"
                            >
                              Configure Credentials
                            </button>
                          )
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
