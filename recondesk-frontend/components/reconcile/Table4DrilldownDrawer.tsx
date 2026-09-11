"use client";

import { useEffect, useState } from "react";
import useSWR from "swr";
import { formatINR } from "@/lib/format";
import { gstr3bApi, Table4DrilldownResponse } from "@/lib/api";

interface Table4DrilldownDrawerProps {
  runId: string;
  authToken: string;
  rowId: string | null;
  rowLabel: string;
  onClose: () => void;
}

export function Table4DrilldownDrawer({
  runId,
  authToken,
  rowId,
  rowLabel,
  onClose,
}: Table4DrilldownDrawerProps) {
  const [search, setSearch] = useState("");
  const [page, setPage] = useState(1);

  // Reset pagination when rowId changes
  useEffect(() => {
    setPage(1);
    setSearch("");
  }, [rowId]);

  const { data, isLoading, error } = useSWR<Table4DrilldownResponse>(
    authToken && runId && rowId
      ? [`table4-drilldown`, runId, rowId, page, search]
      : null,
    () => gstr3bApi.getTable4Drilldown(authToken, runId, rowId!, page, 50, search || undefined),
    { keepPreviousData: true }
  );

  if (!rowId) return null;

  const records = data?.records || [];
  const totals = data?.totals;
  const totalRecords = data?.total_records || 0;
  const totalPages = Math.ceil(totalRecords / 50) || 1;

  return (
    <div className="fixed inset-0 z-50 overflow-hidden bg-black/40 backdrop-blur-sm transition-opacity">
      <div className="fixed inset-y-0 right-0 flex max-w-full pl-10">
        <div className="w-screen max-w-4xl bg-white shadow-2xl flex flex-col">
          {/* Header */}
          <div className="border-b border-[#E5E7EB] px-6 py-4 flex items-center justify-between bg-[#FAFAFA]">
            <div>
              <div className="flex items-center gap-2">
                <span className="rounded bg-black px-2 py-0.5 text-[11px] font-bold text-white uppercase tracking-wider">
                  {rowId}
                </span>
                <h2 className="text-[16px] font-semibold text-gray-900">
                  {rowLabel}
                </h2>
              </div>
              <p className="mt-1 text-[12px] text-gray-500">
                Itemized invoice ledger and contributing adjustments ({totalRecords} items)
              </p>
            </div>
            <button
              onClick={onClose}
              className="rounded-lg p-2 text-gray-400 hover:bg-gray-100 hover:text-gray-700 transition"
              title="Close drawer"
            >
              <svg className="w-5 h-5" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M6 18L18 6M6 6l12 12" />
              </svg>
            </button>
          </div>

          {/* Subheader: Totals & Search */}
          <div className="border-b border-[#E5E7EB] px-6 py-3 flex flex-wrap items-center justify-between gap-4 bg-white">
            <div className="flex items-center gap-4 text-[13px]">
              <div className="flex items-baseline gap-1.5">
                <span className="text-gray-500 font-medium">IGST:</span>
                <span className="font-semibold text-gray-900 tabular-nums">{formatINR(totals?.igst || 0)}</span>
              </div>
              <div className="flex items-baseline gap-1.5">
                <span className="text-gray-500 font-medium">CGST:</span>
                <span className="font-semibold text-gray-900 tabular-nums">{formatINR(totals?.cgst || 0)}</span>
              </div>
              <div className="flex items-baseline gap-1.5">
                <span className="text-gray-500 font-medium">SGST:</span>
                <span className="font-semibold text-gray-900 tabular-nums">{formatINR(totals?.sgst || 0)}</span>
              </div>
              <div className="flex items-baseline gap-1.5">
                <span className="text-gray-500 font-medium">Total:</span>
                <span className="font-bold text-gray-900 tabular-nums">{formatINR(totals?.total_tax || 0)}</span>
              </div>
            </div>

            <div className="relative min-w-[240px]">
              <input
                type="text"
                value={search}
                onChange={(e) => {
                  setSearch(e.target.value);
                  setPage(1);
                }}
                placeholder="Search GSTIN, supplier, invoice..."
                className="w-full rounded-lg border border-[#E5E7EB] px-3 py-1.5 text-[12px] placeholder:text-gray-400 focus:border-black focus:outline-none"
              />
            </div>
          </div>

          {/* Table Content */}
          <div className="flex-1 overflow-y-auto p-6">
            {isLoading && !data && (
              <div className="flex flex-col items-center justify-center py-20 gap-3">
                <svg className="h-6 w-6 animate-spin text-black" fill="none" viewBox="0 0 24 24">
                  <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
                  <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8v8z" />
                </svg>
                <p className="text-[12px] text-gray-400">Loading ledger evidence…</p>
              </div>
            )}

            {error && (
              <div className="rounded-lg bg-red-50 p-4 text-[13px] text-red-600">
                Failed to load ledger records. Please retry.
              </div>
            )}

            {!isLoading && records.length === 0 && (
              <div className="text-center py-20 text-gray-400 text-[13px]">
                No contributing records found for {rowId}.
              </div>
            )}

            {records.length > 0 && (
              <div className="overflow-x-auto rounded-lg border border-[#E5E7EB]">
                <table className="w-full text-left text-[12px] border-collapse">
                  <thead className="bg-[#F8FAFC] text-[11px] font-semibold text-gray-500 uppercase tracking-wider border-b border-[#E5E7EB]">
                    <tr>
                      <th className="px-3 py-2.5">Doc</th>
                      <th className="px-3 py-2.5">Supplier GSTIN / Name</th>
                      <th className="px-3 py-2.5">Invoice #</th>
                      <th className="px-3 py-2.5">Date</th>
                      <th className="px-3 py-2.5 text-right">IGST</th>
                      <th className="px-3 py-2.5 text-right">CGST</th>
                      <th className="px-3 py-2.5 text-right">SGST</th>
                      <th className="px-3 py-2.5 text-right">Total Tax</th>
                      <th className="px-3 py-2.5">Statutory Reason</th>
                      <th className="px-3 py-2.5">Disposition</th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-[#E5E7EB]">
                    {records.map((r, idx) => (
                      <tr key={r.id || idx} className="hover:bg-gray-50/75 transition">
                        <td className="px-3 py-2 whitespace-nowrap font-medium text-gray-600">
                          {r.doc_type === "CREDIT_NOTE" ? (
                            <span className="rounded bg-red-50 px-1.5 py-0.5 text-[10px] font-semibold text-red-700">
                              CN
                            </span>
                          ) : r.type === "ADJUSTMENT" ? (
                            <span className="rounded bg-violet-50 px-1.5 py-0.5 text-[10px] font-semibold text-violet-700">
                              ADJ
                            </span>
                          ) : (
                            <span className="rounded bg-gray-100 px-1.5 py-0.5 text-[10px] font-semibold text-gray-700">
                              INV
                            </span>
                          )}
                        </td>
                        <td className="px-3 py-2 max-w-[180px]">
                          <p className="font-semibold text-gray-900 truncate" title={r.supplier_name}>
                            {r.supplier_name || "—"}
                          </p>
                          <p className="text-[11px] font-mono text-gray-500">{r.supplier_gstin}</p>
                        </td>
                        <td className="px-3 py-2 font-mono text-gray-800 whitespace-nowrap">
                          {r.invoice_number || "—"}
                        </td>
                        <td className="px-3 py-2 text-gray-500 whitespace-nowrap">
                          {r.invoice_date || "—"}
                        </td>
                        <td className="px-3 py-2 text-right tabular-nums text-gray-800">
                          {r.igst !== 0 ? formatINR(r.igst) : "—"}
                        </td>
                        <td className="px-3 py-2 text-right tabular-nums text-gray-800">
                          {r.cgst !== 0 ? formatINR(r.cgst) : "—"}
                        </td>
                        <td className="px-3 py-2 text-right tabular-nums text-gray-800">
                          {r.sgst !== 0 ? formatINR(r.sgst) : "—"}
                        </td>
                        <td className="px-3 py-2 text-right font-semibold tabular-nums text-gray-900">
                          {formatINR(r.total_tax)}
                        </td>
                        <td className="px-3 py-2 max-w-[180px] text-gray-600 truncate text-[11px]" title={r.statutory_reason}>
                          {r.statutory_reason || "Eligible credit under Sec 16(2)"}
                        </td>
                        <td className="px-3 py-2 whitespace-nowrap">
                          <span className="rounded-full bg-gray-100 px-2 py-0.5 text-[10px] font-medium text-gray-700">
                            {r.disposition || "MATCHED"}
                          </span>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </div>

          {/* Footer Pagination */}
          {totalPages > 1 && (
            <div className="border-t border-[#E5E7EB] px-6 py-3 flex items-center justify-between bg-[#FAFAFA]">
              <p className="text-[12px] text-gray-500">
                Page <span className="font-semibold text-gray-900">{page}</span> of{" "}
                <span className="font-semibold text-gray-900">{totalPages}</span>
              </p>
              <div className="flex gap-2">
                <button
                  disabled={page <= 1}
                  onClick={() => setPage((p) => Math.max(1, p - 1))}
                  className="rounded border border-[#E5E7EB] px-3 py-1 text-[12px] font-medium text-gray-700 hover:bg-white disabled:opacity-40"
                >
                  Previous
                </button>
                <button
                  disabled={page >= totalPages}
                  onClick={() => setPage((p) => p + 1)}
                  className="rounded border border-[#E5E7EB] px-3 py-1 text-[12px] font-medium text-gray-700 hover:bg-white disabled:opacity-40"
                >
                  Next
                </button>
              </div>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
