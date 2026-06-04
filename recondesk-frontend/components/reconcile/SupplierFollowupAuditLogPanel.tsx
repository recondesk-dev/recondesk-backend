"use client";

import { Loader2 } from "lucide-react";
import { useMemo, useState } from "react";
import useSWR from "swr";

import {
  FollowupAuditFilters,
  SupplierFollowupAuditTable,
} from "@/components/reconcile/SupplierFollowupAuditTable";
import { sectionContainerClass, SectionHeader } from "@/components/reconcile/ResultsUi";
import { followupAuditApi } from "@/lib/api";

const EMPTY_RUN =
  "No follow-up letters generated for this run yet.";

export function SupplierFollowupAuditLogPanel({
  runId,
  authToken,
}: {
  runId: string;
  authToken: string;
}) {
  const [statusFilter, setStatusFilter] = useState("");
  const [gstinFilter, setGstinFilter] = useState("");

  const swrKey =
    runId && authToken
      ? (["followup-audit-run", runId, authToken] as const)
      : null;

  const { data, error, isLoading, mutate } = useSWR(
    swrKey,
    ([, rid, token]) => followupAuditApi.listForRun(token, rid),
    { revalidateOnFocus: false }
  );

  const supplierOptions = useMemo(() => {
    const set = new Set<string>();
    for (const row of data ?? []) {
      if (row.supplier_gstin) set.add(row.supplier_gstin);
    }
    return Array.from(set).sort();
  }, [data]);

  const filteredRows = useMemo(() => {
    let rows = data ?? [];
    if (statusFilter) {
      rows = rows.filter((r) => r.status === statusFilter);
    }
    if (gstinFilter) {
      rows = rows.filter((r) => r.supplier_gstin === gstinFilter);
    }
    return rows;
  }, [data, gstinFilter, statusFilter]);

  return (
    <div className={sectionContainerClass}>
      <SectionHeader title="Follow-up Log" dotColor="#7C3AED" />
      <FollowupAuditFilters
        status={statusFilter}
        onStatusChange={setStatusFilter}
        supplierGstin={gstinFilter}
        onSupplierGstinChange={setGstinFilter}
        supplierGstinOptions={supplierOptions}
      />
      {error && (
        <div className="mb-4 rounded-lg border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-800">
          Failed to load follow-up log.{" "}
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
          emptyMessage={EMPTY_RUN}
        />
      )}
    </div>
  );
}
