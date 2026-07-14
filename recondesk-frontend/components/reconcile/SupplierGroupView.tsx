"use client";

import { ChevronDown, ChevronRight, Loader2 } from "lucide-react";
import { Fragment, type ReactNode } from "react";

import { AmountDisplay, ImpactBadge, tableRowClass } from "@/components/reconcile/ResultsUi";
import { GstinCell } from "@/components/ui/GstinCell";
import { HoverTextCell } from "@/components/ui/HoverTextCell";
import type { SupplierGroup } from "@/lib/groupBySupplier";
import { formatINR } from "@/lib/format";

type Props<T extends { id: string; amount: number }> = {
  groups: SupplierGroup<T>[];
  expandedGstin: string | null;
  onToggleExpand: (gstin: string) => void;
  amountLabel: string;
  grandTotal?: number;
  loading?: boolean;
  onGenerateFollowup?: (invoices: T[]) => void;
  followupDisabled?: boolean;
  renderInvoices: (invoices: T[], group: SupplierGroup<T>) => ReactNode;
};

function impactFor(total: number, grand: number): "high" | "medium" | "low" {
  if (grand <= 0) return "low";
  if (total >= grand * 0.5) return "high";
  if (total >= grand * 0.1) return "medium";
  return "low";
}

export function SupplierGroupView<T extends { id: string; amount: number }>({
  groups,
  expandedGstin,
  onToggleExpand,
  amountLabel,
  grandTotal = 0,
  loading = false,
  onGenerateFollowup,
  followupDisabled = false,
  renderInvoices,
}: Props<T>) {
  if (loading) {
    return (
      <div className="flex items-center justify-center gap-2 py-12 text-sm text-gray-500">
        <Loader2 className="h-4 w-4 animate-spin" />
        Loading suppliers…
      </div>
    );
  }

  if (groups.length === 0) {
    return (
      <p className="py-8 text-center text-sm text-gray-500">
        No suppliers match the current filters.
      </p>
    );
  }

  const colSpan = onGenerateFollowup ? 7 : 6;

  return (
    <div className="overflow-x-auto rounded-xl border border-[#EFEFF2]">
      <table className="w-full min-w-[720px] border-collapse text-left text-[13px]">
        <thead className="bg-[#FAFAFA] text-[11px] uppercase tracking-wide text-gray-500">
          <tr>
            <th className="w-10 px-3 py-2.5 font-medium" aria-label="Expand" />
            <th className="px-3 py-2.5 font-medium">Supplier</th>
            <th className="px-3 py-2.5 font-medium">GSTIN</th>
            <th className="px-3 py-2.5 font-medium text-right">{amountLabel}</th>
            <th className="px-3 py-2.5 font-medium text-right">Invoices</th>
            <th className="px-3 py-2.5 font-medium">Impact</th>
            {onGenerateFollowup ? (
              <th className="px-3 py-2.5 font-medium text-right">Follow-up</th>
            ) : null}
          </tr>
        </thead>
        <tbody>
          {groups.map((group) => {
            const open = expandedGstin === group.gstin;
            return (
              <Fragment key={group.gstin}>
                <tr className={`${tableRowClass} border-t border-[#EFEFF2] bg-white`}>
                  <td className="px-3 py-2.5">
                    <button
                      type="button"
                      aria-expanded={open}
                      aria-label={open ? "Collapse invoices" : "Expand invoices"}
                      className="inline-flex h-7 w-7 items-center justify-center rounded-md text-gray-500 hover:bg-gray-100 hover:text-[var(--ink)]"
                      onClick={() => onToggleExpand(group.gstin)}
                    >
                      {open ? (
                        <ChevronDown className="h-4 w-4" />
                      ) : (
                        <ChevronRight className="h-4 w-4" />
                      )}
                    </button>
                  </td>
                  <td className="px-3 py-2.5">
                    <HoverTextCell
                      text={group.tradeName || `M/s ${group.gstin}`}
                      displayClassName="text-[13px] font-medium text-gray-800"
                    />
                  </td>
                  <td className="px-3 py-2.5 font-mono text-gray-500">
                    <GstinCell gstin={group.gstin} />
                  </td>
                  <td className="px-3 py-2.5 text-right">
                    <AmountDisplay amount={group.totalAmount} />
                  </td>
                  <td className="px-3 py-2.5 text-right tabular-nums text-gray-700">
                    {group.invoiceCount.toLocaleString("en-IN")}
                  </td>
                  <td className="px-3 py-2.5">
                    <ImpactBadge level={impactFor(group.totalAmount, grandTotal)} />
                  </td>
                  {onGenerateFollowup ? (
                    <td className="px-3 py-2.5 text-right">
                      <button
                        type="button"
                        disabled={followupDisabled || group.invoices.length === 0}
                        className="rounded-lg border border-[#E5E7EB] bg-white px-2 py-1.5 text-[10px] font-medium leading-tight text-[var(--ink)] hover:bg-[#F5F5F6] disabled:cursor-not-allowed disabled:opacity-50"
                        onClick={() => onGenerateFollowup(group.invoices)}
                      >
                        Generate Follow-up Letter
                      </button>
                    </td>
                  ) : null}
                </tr>
                {open ? (
                  <tr className="border-t border-[#EFEFF2] bg-[#FBFBFC]">
                    <td colSpan={colSpan} className="px-3 py-3">
                      <div className="mb-2 text-[11px] font-medium uppercase tracking-wide text-gray-400">
                        {group.invoiceCount} invoice
                        {group.invoiceCount === 1 ? "" : "s"} ·{" "}
                        {formatINR(group.totalAmount)}
                      </div>
                      {renderInvoices(group.invoices, group)}
                    </td>
                  </tr>
                ) : null}
              </Fragment>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}
