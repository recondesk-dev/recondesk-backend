"use client";

import { Loader2 } from "lucide-react";
import { useCallback, useEffect, useMemo, useState } from "react";
import useSWR from "swr";

import { ReconcilePaginationFooter } from "@/components/reconcile/ReconcilePaginationFooter";
import {
  FollowupAuditFilters,
  SupplierFollowupAuditTable,
} from "@/components/reconcile/SupplierFollowupAuditTable";
import { sectionContainerClass, SectionHeader } from "@/components/reconcile/ResultsUi";
import { followupAuditApi } from "@/lib/api";
import {
  isValidReconcileTablePageSize,
  persistReconcileTablePageSize,
  readStoredReconcileTablePageSize,
  RECONCILE_PAGE_SIZE_STORAGE_KEYS,
  RECONCILE_TABLE_PAGE_SIZE_OPTIONS,
} from "@/lib/reconcileTablePageSize";

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
  const [page, setPage] = useState(1);
  const [pageSize, setPageSize] = useState(() =>
    readStoredReconcileTablePageSize(RECONCILE_PAGE_SIZE_STORAGE_KEYS.followup)
  );

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

  const total = filteredRows.length;
  const totalPages = Math.max(1, Math.ceil(total / pageSize));

  useEffect(() => {
    setPage(1);
  }, [statusFilter, gstinFilter, pageSize]);

  useEffect(() => {
    if (page > totalPages) {
      setPage(totalPages);
    }
  }, [page, totalPages]);

  const pagedRows = useMemo(() => {
    const start = (page - 1) * pageSize;
    return filteredRows.slice(start, start + pageSize);
  }, [filteredRows, page, pageSize]);

  const handlePageSizeChange = useCallback((size: number) => {
    if (!isValidReconcileTablePageSize(size)) return;
    setPageSize(size);
    setPage(1);
    persistReconcileTablePageSize(
      RECONCILE_PAGE_SIZE_STORAGE_KEYS.followup,
      size
    );
  }, []);

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
        <>
          <SupplierFollowupAuditTable
            rows={pagedRows}
            emptyMessage={EMPTY_RUN}
          />
          {data && !error && (
            <ReconcilePaginationFooter
              page={page}
              totalPages={totalPages}
              total={total}
              limit={pageSize}
              pageSizeOptions={RECONCILE_TABLE_PAGE_SIZE_OPTIONS}
              pageSize={pageSize}
              onPageSizeChange={handlePageSizeChange}
              onPrev={() => setPage((p) => Math.max(1, p - 1))}
              onNext={() => setPage((p) => Math.min(totalPages, p + 1))}
            />
          )}
        </>
      )}
    </div>
  );
}
