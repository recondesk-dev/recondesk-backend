"use client";

import { Loader2 } from "lucide-react";
import useSWR from "swr";

import {
  InrAmount,
  StatCard,
  statCardValueClass,
  tableCellClass,
  tableClass,
  tableHeadCellClass,
  tableHeadClass,
  tableRowClass,
  tableWrapClass,
} from "@/components/reconcile/ResultsUi";
import { apiFetch } from "@/lib/api";
import {
  formatRule37ActionLabel,
  formatRule37ActionTimeIst,
  type Rule37SummaryResponse,
} from "@/lib/rule37Summary";

const EMPTY_ACTIONS =
  "No actions taken yet for this period.";

export function Rule37SummarySection({
  runId,
  authToken,
  refreshKey = 0,
}: {
  runId: string;
  authToken: string;
  refreshKey?: number;
}) {
  const swrKey =
    runId && authToken
      ? (["rule37-summary", runId, authToken, refreshKey] as const)
      : null;

  const { data, error, isLoading, mutate } = useSWR(
    swrKey,
    ([, rid, token]) =>
      apiFetch<Rule37SummaryResponse>(
        `/api/reconcile/runs/${encodeURIComponent(rid)}/rule37/summary`,
        { token }
      ),
    { revalidateOnFocus: false }
  );

  if (error) {
    return (
      <div className="mb-6 rounded-lg border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-800">
        Failed to load Rule 37 summary.{" "}
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
        Loading summary…
      </p>
    );
  }

  if (!data) return null;

  const { summary, action_history: actionHistory } = data;

  return (
    <div className="mb-6 space-y-6">
      <div className="grid w-full min-w-0 grid-cols-2 gap-3 md:[grid-template-columns:repeat(4,minmax(0,1fr))]">
        <div className="min-w-0 overflow-hidden rounded-2xl">
          <StatCard
            label="Total ITC at Risk"
            accent="neutral"
            value={
              <InrAmount
                amount={summary.total_itc_at_risk}
                sizeClass={statCardValueClass}
                numberColorClass="text-gray-800"
              />
            }
          />
        </div>
        <div className="min-w-0 overflow-hidden rounded-2xl">
          <StatCard
            label="ITC Saved"
            accent="saved"
            value={
              <InrAmount
                amount={summary.itc_saved}
                sizeClass={statCardValueClass}
                numberColorClass="text-green-700"
              />
            }
          />
        </div>
        <div className="min-w-0 overflow-hidden rounded-2xl">
          <StatCard
            label="ITC Reversed"
            accent="reversed"
            value={
              <InrAmount
                amount={summary.itc_reversed}
                sizeClass={statCardValueClass}
                numberColorClass="text-red-600"
              />
            }
          />
        </div>
        <div className="min-w-0 overflow-hidden rounded-2xl">
          <StatCard
            label="Pending Action"
            accent="pending"
            value={
              <InrAmount
                amount={summary.pending_action}
                sizeClass={statCardValueClass}
                numberColorClass="text-amber-700"
              />
            }
          />
        </div>
      </div>

      <div>
        <h3 className="mb-3 text-[13px] font-semibold uppercase tracking-wider text-gray-500">
          Action History
        </h3>
        {actionHistory.length === 0 ? (
          <p className="py-6 text-center text-[13px] text-gray-500">
            {EMPTY_ACTIONS}
          </p>
        ) : (
          <div className={tableWrapClass}>
            <table className={tableClass}>
              <thead className={tableHeadClass}>
                <tr>
                  <th className={tableHeadCellClass}>Invoice #</th>
                  <th className={tableHeadCellClass}>Supplier GSTIN</th>
                  <th className={`${tableHeadCellClass} text-right`}>Amount</th>
                  <th className={tableHeadCellClass}>Action</th>
                  <th className={tableHeadCellClass}>Date</th>
                  <th className={tableHeadCellClass}>By</th>
                </tr>
              </thead>
              <tbody>
                {actionHistory.map((row) => (
                  <tr key={row.id} className={tableRowClass}>
                    <td className={tableCellClass}>{row.invoice_number || "—"}</td>
                    <td
                      className={`${tableCellClass} font-mono text-[12px] text-gray-500`}
                    >
                      {row.supplier_gstin || "—"}
                    </td>
                    <td className={`${tableCellClass} text-right font-semibold`}>
                      <InrAmount amount={row.amount} />
                    </td>
                    <td className={tableCellClass}>
                      {formatRule37ActionLabel(row.action)}
                    </td>
                    <td className={`${tableCellClass} text-[13px] text-gray-600`}>
                      {formatRule37ActionTimeIst(row.created_at)}
                    </td>
                    <td className={tableCellClass}>
                      {row.generated_by_name?.trim() || "—"}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>
    </div>
  );
}
