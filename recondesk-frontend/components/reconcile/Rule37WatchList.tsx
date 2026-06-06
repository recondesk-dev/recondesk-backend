"use client";

import { Loader2 } from "lucide-react";
import useSWR from "swr";

import {
  tableCellClass,
  tableClass,
  tableHeadCellClass,
  tableHeadClass,
  tableRowClass,
  tableWrapClass,
} from "@/components/reconcile/ResultsUi";
import { apiFetch } from "@/lib/api";

type Rule37WatchRow = {
  id: string;
  supplier_gstin: string;
  invoice_number: string;
  invoice_date: string;
  deadline: string;
  days_remaining: number | null;
  invoice_amount: number;
  itc_paise: number;
  status: string;
  urgency: string;
};

type Paginated<T> = {
  data: T[];
  total: number;
  page: number;
  limit: number;
  total_pages: number;
};

function daysBadgeClass(days: number | null): string {
  if (days == null) return "bg-gray-100 text-gray-600";
  if (days <= 30) return "bg-amber-100 text-amber-800";
  if (days <= 60) return "bg-yellow-50 text-yellow-700";
  return "bg-gray-100 text-gray-600";
}

function formatDate(value: string): string {
  if (!value) return "—";
  const d = new Date(value);
  if (Number.isNaN(d.getTime())) return value;
  return d.toLocaleDateString("en-IN", {
    day: "2-digit",
    month: "short",
    year: "numeric",
  });
}

/**
 * Fresh invoices (< 180 days old) that are tracked for Rule 37 but are not yet
 * at risk. These show days remaining until the 180-day payment deadline.
 */
export function Rule37WatchList({
  runId,
  authToken,
}: {
  runId: string;
  authToken: string;
}) {
  const swrKey =
    runId && authToken
      ? (["rule37-watch-list", runId, authToken] as const)
      : null;

  const { data, error, isLoading, mutate } = useSWR(
    swrKey,
    ([, rid, token]) =>
      apiFetch<Paginated<Rule37WatchRow>>(
        `/api/reconcile/runs/${encodeURIComponent(rid)}/rule37/watch-list?page=1&limit=250`,
        { token }
      ),
    { revalidateOnFocus: false }
  );

  if (error) {
    return (
      <div className="mb-6 rounded-lg border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-800">
        Failed to load Rule 37 watch list.{" "}
        <button
          type="button"
          className="font-medium underline"
          onClick={() => void mutate()}
        >
          Retry
        </button>
      </div>
    );
  }

  if (isLoading && !data) {
    return (
      <p className="mb-6 flex items-center gap-2 text-sm text-gray-400">
        <Loader2 className="h-4 w-4 animate-spin" />
        Loading watch list…
      </p>
    );
  }

  const rows = data?.data ?? [];
  if (rows.length === 0) return null;

  return (
    <div className="mb-6">
      <div className="mb-3 flex items-center gap-2">
        <h3 className="text-[13px] font-semibold uppercase tracking-wider text-gray-500">
          Watch List
        </h3>
        <span className="rounded-full bg-gray-100 px-2 py-0.5 text-[11px] font-medium text-gray-500">
          {rows.length}
        </span>
      </div>
      <p className="mb-3 text-[13px] text-gray-500">
        Invoices still within the 180-day payment window. ITC is not at risk yet
        — pay the supplier before the deadline to stay compliant.
      </p>
      <div className={tableWrapClass}>
        <table className={tableClass}>
          <thead className={tableHeadClass}>
            <tr>
              <th className={tableHeadCellClass}>Invoice #</th>
              <th className={tableHeadCellClass}>Supplier GSTIN</th>
              <th className={tableHeadCellClass}>Invoice Date</th>
              <th className={tableHeadCellClass}>Payment Deadline</th>
              <th className={`${tableHeadCellClass} text-right`}>
                Days Remaining
              </th>
            </tr>
          </thead>
          <tbody>
            {rows.map((row) => (
              <tr key={row.id} className={tableRowClass}>
                <td className={tableCellClass}>{row.invoice_number || "—"}</td>
                <td
                  className={`${tableCellClass} font-mono text-[12px] text-gray-500`}
                >
                  {row.supplier_gstin || "—"}
                </td>
                <td className={`${tableCellClass} text-[13px] text-gray-600`}>
                  {formatDate(row.invoice_date)}
                </td>
                <td className={`${tableCellClass} text-[13px] text-gray-600`}>
                  {formatDate(row.deadline)}
                </td>
                <td className={`${tableCellClass} text-right`}>
                  <span
                    className={`inline-flex items-center rounded-full px-2.5 py-0.5 text-[12px] font-medium ${daysBadgeClass(row.days_remaining)}`}
                  >
                    {row.days_remaining == null
                      ? "—"
                      : `${row.days_remaining} day${row.days_remaining === 1 ? "" : "s"}`}
                  </span>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
