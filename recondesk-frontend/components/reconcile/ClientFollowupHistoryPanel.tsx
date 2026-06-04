"use client";

import { FileSpreadsheet, Loader2 } from "lucide-react";
import { useCallback, useMemo, useState } from "react";
import useSWR from "swr";

import {
  FollowupAuditFilters,
  SupplierFollowupAuditTable,
} from "@/components/reconcile/SupplierFollowupAuditTable";
import {
  csvDownloadBtnClass,
  sectionContainerClass,
} from "@/components/reconcile/ResultsUi";
import { followupAuditApi } from "@/lib/api";
import { followupHistoryExportFilename } from "@/lib/followupAudit";

const API_URL = (process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000").replace(
  /\/+$/,
  ""
);

const EMPTY_CLIENT =
  "No follow-up letters generated for this client yet.";

export function ClientFollowupHistoryPanel({
  clientId,
  clientGstin,
  authToken,
}: {
  clientId: string;
  clientGstin: string;
  authToken: string;
}) {
  const [statusFilter, setStatusFilter] = useState("");
  const [taxPeriodFilter, setTaxPeriodFilter] = useState("");
  const [exporting, setExporting] = useState(false);
  const [exportError, setExportError] = useState<string | null>(null);

  const swrKey =
    clientId && authToken
      ? (["followup-audit-client", clientId, authToken] as const)
      : null;

  const { data, error, isLoading, mutate } = useSWR(
    swrKey,
    ([, cid, token]) => followupAuditApi.listForClient(token, cid),
    { revalidateOnFocus: false }
  );

  const taxPeriodOptions = useMemo(() => {
    const set = new Set<string>();
    for (const row of data ?? []) {
      if (row.tax_period) set.add(row.tax_period);
    }
    return Array.from(set).sort().reverse();
  }, [data]);

  const filteredRows = useMemo(() => {
    let rows = data ?? [];
    if (statusFilter) {
      rows = rows.filter((r) => r.status === statusFilter);
    }
    if (taxPeriodFilter) {
      rows = rows.filter((r) => r.tax_period === taxPeriodFilter);
    }
    return rows;
  }, [data, statusFilter, taxPeriodFilter]);

  const downloadExcel = useCallback(async () => {
    if (!authToken || !clientId) return;
    setExporting(true);
    setExportError(null);
    try {
      const sp = new URLSearchParams();
      if (statusFilter) sp.set("status", statusFilter);
      if (taxPeriodFilter) sp.set("tax_period", taxPeriodFilter);
      const q = sp.toString();
      const res = await fetch(
        `${API_URL}/api/reconcile/clients/${encodeURIComponent(clientId)}/supplier-followup/audit/export${q ? `?${q}` : ""}`,
        { headers: { Authorization: `Bearer ${authToken}` } }
      );
      if (!res.ok) throw new Error("export failed");
      const blob = await res.blob();
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = followupHistoryExportFilename(clientGstin);
      document.body.appendChild(a);
      a.click();
      a.remove();
      URL.revokeObjectURL(url);
    } catch {
      setExportError("Failed to export follow-up history. Please try again.");
    } finally {
      setExporting(false);
    }
  }, [authToken, clientGstin, clientId, statusFilter, taxPeriodFilter]);

  return (
    <div className={sectionContainerClass}>
      <div className="mb-5 flex flex-wrap items-center justify-between gap-3">
        <h2 className="text-lg font-semibold text-gray-900">Follow-up History</h2>
        <button
          type="button"
          disabled={exporting || isLoading}
          className={csvDownloadBtnClass}
          onClick={() => void downloadExcel()}
        >
          {exporting ? (
            <Loader2 className="h-4 w-4 shrink-0 animate-spin text-gray-400" />
          ) : (
            <FileSpreadsheet className="h-4 w-4 shrink-0 text-gray-500" />
          )}
          Export to Excel
        </button>
      </div>

      {exportError && (
        <div className="mb-4 rounded-lg border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-800">
          {exportError}
        </div>
      )}

      <FollowupAuditFilters
        status={statusFilter}
        onStatusChange={setStatusFilter}
        taxPeriod={taxPeriodFilter}
        onTaxPeriodChange={setTaxPeriodFilter}
        taxPeriodOptions={taxPeriodOptions}
      />

      {error && (
        <div className="mb-4 rounded-lg border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-800">
          Failed to load follow-up history.{" "}
          <button
            type="button"
            className="font-medium underline"
            onClick={() => void mutate()}
          >
            Retry
          </button>
        </div>
      )}

      {isLoading && !data && !error ? (
        <p className="flex items-center gap-2 text-sm text-gray-400">
          <Loader2 className="h-4 w-4 animate-spin" />
          Loading…
        </p>
      ) : (
        <SupplierFollowupAuditTable
          rows={filteredRows}
          showTaxPeriod
          emptyMessage={EMPTY_CLIENT}
        />
      )}
    </div>
  );
}
