"use client";

import { Loader2 } from "lucide-react";
import useSWR from "swr";

import {
  CompactStatAmount,
  InrAmount,
  StatCard,
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
  formatRule37NetPaid,
  formatRule37RemainingUnpaid,
  formatRule37SettlementConsidered,
  formatRule37StatutoryDeduction,
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
        <StatCard
          label="Total ITC at Risk"
          accent="neutral"
          value={
            <CompactStatAmount
              amount={summary.total_itc_at_risk}
              className="text-gray-800"
            />
          }
        />
        <StatCard
          label="ITC Saved"
          accent="saved"
          value={
            <CompactStatAmount
              amount={summary.itc_saved}
              className="text-green-700"
            />
          }
        />
        <StatCard
          label="ITC Reversed"
          accent="reversed"
          value={
            <CompactStatAmount
              amount={summary.itc_reversed}
              className="text-red-600"
            />
          }
        />
        <StatCard
          label="Pending Action"
          accent="pending"
          value={
            <CompactStatAmount
              amount={summary.pending_action}
              className="text-amber-700"
            />
          }
        />
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
                  <th className={`${tableHeadCellClass} text-right`}>
                    Net Paid to Supplier
                  </th>
                  <th className={`${tableHeadCellClass} text-right`}>
                    TDS / Statutory Deduction
                  </th>
                  <th className={`${tableHeadCellClass} text-right`}>
                    Settlement Considered
                  </th>
                  <th className={`${tableHeadCellClass} text-right`}>
                    Remaining Unpaid
                  </th>
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
                    <td className={`${tableCellClass} text-right text-[13px]`}>
                      {formatRule37NetPaid(row.amount_paid)}
                    </td>
                    <td className={`${tableCellClass} text-right text-[13px]`}>
                      {formatRule37StatutoryDeduction(row.tds_deducted)}
                    </td>
                    <td className={`${tableCellClass} text-right text-[13px] font-semibold`}>
                      {formatRule37SettlementConsidered(row)}
                    </td>
                    <td className={`${tableCellClass} text-right text-[13px]`}>
                      {formatRule37RemainingUnpaid(row)}
                    </td>
                    <td className={tableCellClass}>
                      {formatRule37ActionLabel(row.action)}
                      {row.payment_coverage === "partial" ? (
                        <span className="ml-1 text-[11px] text-amber-600">
                          (Partial)
                        </span>
                      ) : null}
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
