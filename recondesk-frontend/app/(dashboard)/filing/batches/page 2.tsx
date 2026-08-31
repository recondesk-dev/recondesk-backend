"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useState } from "react";
import { CheckSquare, Layers, Loader2, Play, Plus, RefreshCw, Square } from "lucide-react";
import useSWR from "swr";

import {
  SectionHeader,
  pageContentClass,
  sectionContainerClass,
} from "@/components/reconcile/ResultsUi";
import {
  clientsApi,
  filingApi,
  isApiError,
  type ClientGstin,
  type FilingBatch,
} from "@/lib/api";
import { useAccessToken } from "@/lib/hooks/useAccessToken";

export default function FilingBatchesPage() {
  const router = useRouter();
  const tokenState = useAccessToken();
  const token = typeof tokenState === "string" && tokenState.length > 0 ? tokenState : null;

  const [period, setPeriod] = useState("2026-07");
  const [selectedClientIds, setSelectedClientIds] = useState<string[]>([]);
  const [showCreateModal, setShowCreateModal] = useState(false);
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [errorMessage, setErrorMessage] = useState<string | null>(null);

  const batchesKey = token ? (["filing-batches", token] as const) : null;
  const { data: batchesData, mutate: mutateBatches, isLoading: batchesLoading } = useSWR(
    batchesKey,
    ([, t]) => filingApi.listBatches(t),
    { refreshInterval: 5000 }
  );

  const clientsKey = token ? (["filing-clients", token] as const) : null;
  const { data: clients, isLoading: clientsLoading } = useSWR(
    clientsKey,
    ([, t]) => clientsApi.list(t)
  );

  const batches = batchesData?.batches || [];

  const handleSelectAllClients = () => {
    if (!clients) return;
    if (selectedClientIds.length === clients.length) {
      setSelectedClientIds([]);
    } else {
      setSelectedClientIds(clients.map((c) => c.id));
    }
  };

  const toggleClientSelection = (id: string) => {
    setSelectedClientIds((prev) =>
      prev.includes(id) ? prev.filter((item) => item !== id) : [...prev, id]
    );
  };

  const handleCreateBatch = async () => {
    if (!token || !period.trim() || selectedClientIds.length === 0) {
      setErrorMessage("Please select a period and at least one client GSTIN.");
      return;
    }
    setIsSubmitting(true);
    setErrorMessage(null);
    try {
      const newBatch = await filingApi.createBatch(token, {
        period: period.trim(),
        client_gstin_ids: selectedClientIds,
        return_type: "gstr-1",
      });
      setShowCreateModal(false);
      setSelectedClientIds([]);
      mutateBatches();
      router.push(`/filing/batches/${newBatch.id}`);
    } catch (err) {
      setErrorMessage(
        isApiError(err) ? err.detail : err instanceof Error ? err.message : "Failed to create batch"
      );
    } finally {
      setIsSubmitting(false);
    }
  };

  if (tokenState === null || batchesLoading) {
    return (
      <div className="flex min-h-[40vh] items-center justify-center px-8 text-[13px] text-gray-500">
        <Loader2 className="mr-2 h-4 w-4 animate-spin" /> Loading batches…
      </div>
    );
  }

  return (
    <div className={pageContentClass}>
      <div className="mb-6 flex flex-wrap items-center justify-between gap-4">
        <div>
          <h1 className="text-2xl font-semibold tracking-tight text-[var(--ink)]">
            Bulk GSTR-1 Return Filing
          </h1>
          <p className="text-sm text-gray-500">
            Orchestrate GSTR-1 Save $\rightarrow$ Status $\rightarrow$ Proceed for multiple client GSTINs in batch mode.
          </p>
        </div>
        <div className="flex items-center gap-3">
          <button
            type="button"
            onClick={() => mutateBatches()}
            className="inline-flex items-center gap-1.5 rounded-full bg-white px-4 py-2 text-[13px] font-medium text-gray-700 shadow-sm hover:bg-gray-50"
          >
            <RefreshCw className="h-3.5 w-3.5" /> Refresh
          </button>
          <button
            type="button"
            onClick={() => setShowCreateModal(true)}
            className="inline-flex items-center gap-2 rounded-full bg-[var(--ink)] px-5 py-2 text-[13px] font-semibold text-white shadow hover:opacity-90"
          >
            <Plus className="h-4 w-4" /> Start Bulk GSTR-1 Filing
          </button>
        </div>
      </div>

      <section className={sectionContainerClass}>
        <SectionHeader title="Filing Batches" dotColor="#111111" />

        {batches.length === 0 ? (
          <div className="my-8 rounded-2xl border border-dashed border-gray-200 p-8 text-center">
            <Layers className="mx-auto h-8 w-8 text-gray-400" />
            <h3 className="mt-2 text-sm font-semibold text-gray-900">No bulk filing batches yet</h3>
            <p className="mt-1 text-xs text-gray-500">
              Create a new batch to process GSTR-1 returns for multiple client GSTINs simultaneously.
            </p>
            <button
              type="button"
              onClick={() => setShowCreateModal(true)}
              className="mt-4 inline-flex items-center gap-1.5 rounded-full bg-[var(--ink)] px-4 py-2 text-[13px] font-semibold text-white"
            >
              <Plus className="h-4 w-4" /> Create First Batch
            </button>
          </div>
        ) : (
          <div className="mt-4 overflow-x-auto">
            <table className="w-full text-left text-[13px]">
              <thead>
                <tr className="border-b border-gray-100 text-[11px] font-semibold uppercase tracking-wider text-gray-400">
                  <th className="pb-3 pl-2">Batch ID / Period</th>
                  <th className="pb-3">Return Type</th>
                  <th className="pb-3">Status</th>
                  <th className="pb-3">Progress</th>
                  <th className="pb-3">Counts (Total / Saved / EVC / Filed / Failed)</th>
                  <th className="pb-3 pr-2 text-right">Created</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-gray-100 font-medium">
                {batches.map((b: FilingBatch) => {
                  const completedCount = (b.filed_count || 0) + (b.evc_pending_count || 0) + (b.failed_count || 0);
                  const progressPct = b.total_count > 0 ? Math.round((completedCount / b.total_count) * 100) : 0;

                  return (
                    <tr key={b.id} className="hover:bg-gray-50/50">
                      <td className="py-3.5 pl-2">
                        <Link
                          href={`/filing/batches/${b.id}`}
                          className="font-semibold text-[var(--ink)] underline-offset-2 hover:underline"
                        >
                          Period {b.period}
                        </Link>
                        <div className="text-[11px] font-normal text-gray-400 font-mono">
                          {b.id.slice(0, 8)}…
                        </div>
                      </td>
                      <td className="py-3.5 uppercase font-semibold text-gray-700">
                        {b.return_type}
                      </td>
                      <td className="py-3.5">
                        <span
                          className={`inline-flex items-center rounded-full px-2.5 py-0.5 text-[11px] font-semibold capitalize ${
                            b.status === "completed"
                              ? "bg-emerald-50 text-emerald-700"
                              : b.status === "in_progress"
                              ? "bg-amber-50 text-amber-700"
                              : b.status === "partially_completed"
                              ? "bg-blue-50 text-blue-700"
                              : "bg-red-50 text-red-700"
                          }`}
                        >
                          {b.status.replace("_", " ")}
                        </span>
                      </td>
                      <td className="py-3.5 w-44">
                        <div className="flex items-center gap-2">
                          <div className="h-1.5 w-full rounded-full bg-gray-100 overflow-hidden">
                            <div
                              className="h-full bg-emerald-500 transition-all duration-300"
                              style={{ width: `${progressPct}%` }}
                            />
                          </div>
                          <span className="text-[11px] font-medium text-gray-500">
                            {progressPct}%
                          </span>
                        </div>
                      </td>
                      <td className="py-3.5 text-gray-600">
                        <span className="font-semibold">{b.total_count}</span> total ·{" "}
                        <span className="text-emerald-600 font-semibold">{b.saved_count || 0}</span> saved ·{" "}
                        <span className="text-purple-600 font-semibold">{b.evc_pending_count || 0}</span> EVC pending ·{" "}
                        <span className="text-blue-600 font-semibold">{b.filed_count || 0}</span> filed ·{" "}
                        <span className="text-red-600 font-semibold">{b.failed_count || 0}</span> failed
                      </td>
                      <td className="py-3.5 pr-2 text-right text-gray-400 text-[12px]">
                        {new Date(b.created_at).toLocaleString("en-IN", {
                          dateStyle: "short",
                          timeStyle: "short",
                        })}
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        )}
      </section>

      {/* Create Batch Modal */}
      {showCreateModal ? (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 backdrop-blur-sm p-4">
          <div className="w-full max-w-lg rounded-2xl bg-white p-6 shadow-2xl space-y-5">
            <div className="flex items-center justify-between border-b pb-3">
              <h3 className="text-lg font-semibold text-gray-900">
                New Bulk GSTR-1 Filing Batch
              </h3>
              <button
                type="button"
                onClick={() => setShowCreateModal(false)}
                className="text-gray-400 hover:text-gray-600"
              >
                ✕
              </button>
            </div>

            <div>
              <label className="block text-[12px] font-medium text-gray-600">
                Return Period (YYYY-MM)
              </label>
              <input
                type="text"
                value={period}
                onChange={(e) => setPeriod(e.target.value)}
                placeholder="2026-07"
                className="mt-1 h-10 w-full rounded-xl border border-gray-200 px-3 text-sm focus:outline-none focus:ring-2 focus:ring-black/10"
              />
            </div>

            <div>
              <div className="flex items-center justify-between mb-1.5">
                <label className="text-[12px] font-medium text-gray-600">
                  Select Client GSTINs ({selectedClientIds.length} of {clients?.length || 0} selected)
                </label>
                <button
                  type="button"
                  onClick={handleSelectAllClients}
                  className="text-[11px] font-semibold text-[var(--ink)] hover:underline"
                >
                  {selectedClientIds.length === (clients?.length || 0) ? "Deselect All" : "Select All"}
                </button>
              </div>

              <div className="max-h-56 overflow-y-auto rounded-xl border border-gray-100 divide-y divide-gray-50">
                {clientsLoading ? (
                  <div className="p-4 text-center text-xs text-gray-400">Loading client GSTINs…</div>
                ) : (clients || []).length === 0 ? (
                  <div className="p-4 text-center text-xs text-gray-400">No active clients found</div>
                ) : (
                  (clients || []).map((c: ClientGstin) => {
                    const isSelected = selectedClientIds.includes(c.id);
                    return (
                      <div
                        key={c.id}
                        onClick={() => toggleClientSelection(c.id)}
                        className="flex items-center justify-between p-2.5 hover:bg-gray-50 cursor-pointer"
                      >
                        <div className="flex items-center gap-2.5">
                          {isSelected ? (
                            <CheckSquare className="h-4 w-4 text-[var(--ink)]" />
                          ) : (
                            <Square className="h-4 w-4 text-gray-300" />
                          )}
                          <div>
                            <div className="text-[13px] font-medium text-gray-800">
                              {c.trade_name || c.legal_name || "Client"}
                            </div>
                            <div className="text-[11px] font-mono text-gray-400">{c.gstin}</div>
                          </div>
                        </div>
                      </div>
                    );
                  })
                )}
              </div>
            </div>

            {errorMessage ? (
              <div className="rounded-xl bg-red-50 p-3 text-xs text-red-600">{errorMessage}</div>
            ) : null}

            <div className="flex items-center justify-end gap-3 pt-2">
              <button
                type="button"
                onClick={() => setShowCreateModal(false)}
                className="rounded-full px-4 py-2 text-xs font-semibold text-gray-600 hover:bg-gray-100"
              >
                Cancel
              </button>
              <button
                type="button"
                disabled={isSubmitting || selectedClientIds.length === 0}
                onClick={handleCreateBatch}
                className="inline-flex items-center gap-1.5 rounded-full bg-[var(--ink)] px-5 py-2 text-xs font-semibold text-white hover:opacity-90 disabled:opacity-40"
              >
                {isSubmitting ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <Play className="h-3.5 w-3.5" />}
                Launch Bulk Batch
              </button>
            </div>
          </div>
        </div>
      ) : null}
    </div>
  );
}
