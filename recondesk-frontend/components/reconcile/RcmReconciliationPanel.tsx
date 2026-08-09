"use client";

import { AlertCircle, CheckCircle2, ChevronDown, Info, Loader2 } from "lucide-react";
import { useState } from "react";
import useSWR from "swr";

import {
  SectionHeader,
  sectionContainerClass,
  statCardsGridClass,
  statCardValueClass,
  tableCellClass,
  tableClass,
  tableHeadCellClass,
  tableHeadClass,
  tableRowClass,
  tableWrapClass,
} from "@/components/reconcile/ResultsUi";
import { apiFetch } from "@/lib/api";

type RcmVariance = {
  reason_code: string;
  description: string;
  diff_paise: number;
  diff: string;
  pr_tax: string;
  gstr3b_31d_tax: string;
  gstr3b_rcm_itc: string;
};

type RcmFlaggedRow = {
  invoice_number: string;
  supplier_gstin: string;
  supplier_name: string;
  invoice_date: string;
  hsn_sac: string | null;
  taxable_value: string;
  total_tax: string;
  category: string;
  reason_code: string;
  confidence: "HIGH" | "MEDIUM" | "LOW" | string;
  pending_review: boolean;
  explanation: string;
};

type RcmTieOutResponse = {
  gstin: string;
  ret_period: string;
  is_clean: boolean;
  summary_by_reason: Record<string, number>;
  pr_summary: {
    taxable_value_paise: number;
    taxable_value: string;
    total_tax_paise: number;
    total_tax: string;
    flagged_count: number;
  };
  gstr3b_summary: {
    table_31d_taxable_value_paise: number;
    table_31d_taxable_value: string;
    table_31d_tax_paise: number;
    table_31d_tax: string;
    table_4a3_itc_paise: number;
    table_4a3_itc: string;
    table_4a2_itc_paise: number;
    table_4a2_itc: string;
    total_rcm_itc_claimed_paise: number;
    total_rcm_itc_claimed: string;
  };
  variances: RcmVariance[];
  flagged_rows: RcmFlaggedRow[];
  cash_ledger_note: string;
};

function confidenceBadgeClass(confidence: string): string {
  switch (confidence) {
    case "HIGH":
      return "bg-emerald-50 text-emerald-700 ring-1 ring-emerald-200";
    case "MEDIUM":
      return "bg-amber-50 text-amber-800 ring-1 ring-amber-200";
    case "LOW":
      return "bg-gray-100 text-gray-600 ring-1 ring-gray-200";
    default:
      return "bg-gray-100 text-gray-600 ring-1 ring-gray-200";
  }
}

function reasonBadgeLabel(code: string): string {
  switch (code) {
    case "REASON_RCM_UNDERPAID":
      return "Underpaid RCM Liability";
    case "REASON_RCM_ITC_BEFORE_PAYMENT":
      return "ITC Claimed Before Payment";
    case "REASON_RCM_ITC_NOT_CLAIMED":
      return "Unclaimed RCM Credit";
    case "REASON_RCM_TIMING_MISMATCH":
      return "Timing Shift";
    default:
      return code.replace("REASON_", "").replace(/_/g, " ");
  }
}

function reasonBadgeClass(code: string): string {
  switch (code) {
    case "REASON_RCM_UNDERPAID":
    case "REASON_RCM_ITC_BEFORE_PAYMENT":
      return "bg-red-50 text-red-700 ring-1 ring-red-200";
    case "REASON_RCM_ITC_NOT_CLAIMED":
      return "bg-amber-50 text-amber-800 ring-1 ring-amber-200";
    case "REASON_RCM_TIMING_MISMATCH":
      return "bg-blue-50 text-blue-700 ring-1 ring-blue-200";
    default:
      return "bg-gray-100 text-gray-700 ring-1 ring-gray-200";
  }
}

export function RcmReconciliationPanel({
  runId,
  authToken,
}: {
  runId: string;
  authToken: string;
}) {
  const [open, setOpen] = useState(true);

  const { data, error, isLoading, mutate } = useSWR<RcmTieOutResponse>(
    runId && authToken ? `/api/reconcile/runs/${runId}/rcm-tie-out` : null,
    (url: string) => apiFetch<RcmTieOutResponse>(url, { token: authToken })
  );

  if (isLoading) {
    return (
      <div className={sectionContainerClass}>
        <div className="flex items-center gap-2 text-sm text-gray-500">
          <Loader2 className="h-4 w-4 animate-spin" />
          Loading RCM 3-Way Reconciliation...
        </div>
      </div>
    );
  }

  if (error) {
    return (
      <div className={sectionContainerClass}>
        <div className="flex items-center justify-between text-sm text-red-600">
          <span>Failed to load RCM reconciliation data.</span>
          <button
            type="button"
            onClick={() => void mutate()}
            className="font-medium underline hover:text-red-700"
          >
            Retry
          </button>
        </div>
      </div>
    );
  }

  if (!data) return null;

  const totalVariances = data.variances.length;
  const underpaidCount = data.summary_by_reason.REASON_RCM_UNDERPAID || 0;
  const beforePaymentCount = data.summary_by_reason.REASON_RCM_ITC_BEFORE_PAYMENT || 0;
  const unclaimedCount = data.summary_by_reason.REASON_RCM_ITC_NOT_CLAIMED || 0;
  const timingCount = data.summary_by_reason.REASON_RCM_TIMING_MISMATCH || 0;

  return (
    <div className={sectionContainerClass}>
      <button
        type="button"
        className="flex w-full items-center justify-between gap-3 text-left transition-all duration-150"
        onClick={() => setOpen((o) => !o)}
      >
        <span className="flex min-w-0 flex-1 flex-wrap items-center gap-2">
          <span
            className={`h-2.5 w-2.5 shrink-0 rounded-full ${
              data.is_clean ? "bg-emerald-500" : "bg-amber-500"
            }`}
            aria-hidden
          />
          <span className="text-lg font-semibold text-gray-900">
            RCM Reconciliation (Reverse Charge 3-Way Tie-Out)
          </span>

          {data.is_clean ? (
            <span className="inline-flex items-center gap-1 rounded-full bg-emerald-50 px-2.5 py-0.5 text-xs font-semibold text-emerald-700 ring-1 ring-emerald-600/20">
              <CheckCircle2 className="h-3.5 w-3.5" />
              Clean Tie-Out
            </span>
          ) : (
            <span className="inline-flex items-center gap-1 rounded-full bg-amber-50 px-2.5 py-0.5 text-xs font-semibold text-amber-800 ring-1 ring-amber-600/20">
              <AlertCircle className="h-3.5 w-3.5" />
              {totalVariances} Discrepanc{totalVariances === 1 ? "y" : "ies"}
            </span>
          )}
        </span>

        <ChevronDown
          className={`h-5 w-5 shrink-0 text-gray-400 transition-transform duration-150 ${
            open ? "rotate-180" : ""
          }`}
        />
      </button>

      {open && (
        <div className="mt-5 space-y-6 border-t border-[#F0F0F0] pt-5">
          {/* Dashboard Summary Cards */}
          <div className={statCardsGridClass}>
            <div className="rounded-xl border border-[#F0F0F0] bg-gray-50/50 p-4">
              <span className="text-xs font-medium uppercase tracking-wider text-gray-500">
                PR RCM Inward Tax
              </span>
              <p className={`mt-1 ${statCardValueClass} text-gray-900`}>
                {data.pr_summary.total_tax}
              </p>
              <p className="mt-1 text-xs text-gray-500">
                {data.pr_summary.flagged_count} flagged row(s) · Taxable: {data.pr_summary.taxable_value}
              </p>
            </div>

            <div className="rounded-xl border border-[#F0F0F0] bg-gray-50/50 p-4">
              <span className="text-xs font-medium uppercase tracking-wider text-gray-500">
                GSTR-3B Table 3.1(d) Paid
              </span>
              <p className={`mt-1 ${statCardValueClass} text-gray-900`}>
                {data.gstr3b_summary.table_31d_tax}
              </p>
              <p className="mt-1 text-xs text-gray-500">
                Taxable: {data.gstr3b_summary.table_31d_taxable_value}
              </p>
            </div>

            <div className="rounded-xl border border-[#F0F0F0] bg-gray-50/50 p-4">
              <span className="text-xs font-medium uppercase tracking-wider text-gray-500">
                GSTR-3B RCM ITC Claimed
              </span>
              <p className={`mt-1 ${statCardValueClass} text-gray-900`}>
                {data.gstr3b_summary.total_rcm_itc_claimed}
              </p>
              <p className="mt-1 text-xs text-gray-500">
                T4(A)(3): {data.gstr3b_summary.table_4a3_itc} · T4(A)(2): {data.gstr3b_summary.table_4a2_itc}
              </p>
            </div>
          </div>

          {/* Reason Summary Chips */}
          <div className="flex flex-wrap items-center gap-2">
            <span className="text-xs font-medium text-gray-500">Compliance Summary:</span>

            {underpaidCount > 0 && (
              <span className={reasonBadgeClass("REASON_RCM_UNDERPAID") + " px-2.5 py-1 text-xs font-semibold rounded-full"}>
                {underpaidCount} {reasonBadgeLabel("REASON_RCM_UNDERPAID")}
              </span>
            )}
            {beforePaymentCount > 0 && (
              <span className={reasonBadgeClass("REASON_RCM_ITC_BEFORE_PAYMENT") + " px-2.5 py-1 text-xs font-semibold rounded-full"}>
                {beforePaymentCount} {reasonBadgeLabel("REASON_RCM_ITC_BEFORE_PAYMENT")}
              </span>
            )}
            {unclaimedCount > 0 && (
              <span className={reasonBadgeClass("REASON_RCM_ITC_NOT_CLAIMED") + " px-2.5 py-1 text-xs font-semibold rounded-full"}>
                {unclaimedCount} {reasonBadgeLabel("REASON_RCM_ITC_NOT_CLAIMED")}
              </span>
            )}
            {timingCount > 0 && (
              <span className={reasonBadgeClass("REASON_RCM_TIMING_MISMATCH") + " px-2.5 py-1 text-xs font-semibold rounded-full"}>
                {timingCount} {reasonBadgeLabel("REASON_RCM_TIMING_MISMATCH")}
              </span>
            )}
            {totalVariances === 0 && (
              <span className="rounded-full bg-emerald-50 px-2.5 py-1 text-xs font-semibold text-emerald-700 ring-1 ring-emerald-200">
                0 Compliance Flags
              </span>
            )}
          </div>

          {/* Variances Table */}
          {data.variances.length > 0 && (
            <div className="space-y-3">
              <h4 className="text-sm font-semibold text-gray-900">Three-Way Tie-Out Discrepancies</h4>
              <div className={tableWrapClass}>
                <table className={tableClass}>
                  <thead>
                    <tr className="border-b border-[#F0F0F0] bg-gray-50/50">
                      <th className={tableHeadCellClass}>Flag Type</th>
                      <th className={tableHeadCellClass}>Description</th>
                      <th className={tableHeadCellClass + " text-right"}>Diff Amount</th>
                      <th className={tableHeadCellClass + " text-right"}>PR Tax</th>
                      <th className={tableHeadCellClass + " text-right"}>3B 3.1(d) Paid</th>
                      <th className={tableHeadCellClass + " text-right"}>3B RCM ITC</th>
                    </tr>
                  </thead>
                  <tbody>
                    {data.variances.map((v, i) => (
                      <tr key={i} className={tableRowClass}>
                        <td className={tableCellClass}>
                          <span className={reasonBadgeClass(v.reason_code) + " px-2 py-0.5 text-[11px] font-semibold rounded-full"}>
                            {reasonBadgeLabel(v.reason_code)}
                          </span>
                        </td>
                        <td className={tableCellClass + " max-w-md text-xs text-gray-700"}>
                          {v.description}
                        </td>
                        <td className={tableCellClass + " text-right font-semibold text-red-600"}>
                          {v.diff}
                        </td>
                        <td className={tableCellClass + " text-right text-xs text-gray-600"}>
                          {v.pr_tax}
                        </td>
                        <td className={tableCellClass + " text-right text-xs text-gray-600"}>
                          {v.gstr3b_31d_tax}
                        </td>
                        <td className={tableCellClass + " text-right text-xs text-gray-600"}>
                          {v.gstr3b_rcm_itc}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </div>
          )}

          {/* Flagged Purchase Register Inward Rows Table */}
          {data.flagged_rows.length > 0 && (
            <div className="space-y-3">
              <h4 className="text-sm font-semibold text-gray-900">
                RCM-Applicable Transactions Detected in Purchase Register ({data.flagged_rows.length})
              </h4>
              <div className={tableWrapClass}>
                <table className={tableClass}>
                  <thead>
                    <tr className="border-b border-[#F0F0F0] bg-gray-50/50">
                      <th className={tableHeadCellClass}>Invoice</th>
                      <th className={tableHeadCellClass}>Supplier GSTIN</th>
                      <th className={tableHeadCellClass}>Supplier Name</th>
                      <th className={tableHeadCellClass}>HSN / SAC</th>
                      <th className={tableHeadCellClass + " text-right"}>Taxable Value</th>
                      <th className={tableHeadCellClass + " text-right"}>RCM Tax</th>
                      <th className={tableHeadCellClass}>Confidence</th>
                      <th className={tableHeadCellClass}>Category & Explanation</th>
                    </tr>
                  </thead>
                  <tbody>
                    {data.flagged_rows.map((row, idx) => (
                      <tr key={idx} className={tableRowClass}>
                        <td className={tableCellClass + " font-medium text-gray-900 text-xs"}>
                          {row.invoice_number || "—"}
                          {row.invoice_date && (
                            <span className="block text-[11px] font-normal text-gray-400">
                              {row.invoice_date}
                            </span>
                          )}
                        </td>
                        <td className={tableCellClass + " font-mono text-xs text-gray-500"}>
                          {row.supplier_gstin || "—"}
                        </td>
                        <td className={tableCellClass + " text-xs text-gray-700 max-w-[160px] truncate"}>
                          {row.supplier_name || "—"}
                        </td>
                        <td className={tableCellClass + " font-mono text-xs text-gray-600"}>
                          {row.hsn_sac || "—"}
                        </td>
                        <td className={tableCellClass + " text-right font-medium text-xs text-gray-900"}>
                          {row.taxable_value}
                        </td>
                        <td className={tableCellClass + " text-right font-semibold text-xs text-gray-900"}>
                          {row.total_tax}
                        </td>
                        <td className={tableCellClass}>
                          <span className={confidenceBadgeClass(row.confidence) + " px-2 py-0.5 text-[10px] font-semibold rounded-full"}>
                            {row.confidence}
                          </span>
                          {row.pending_review && (
                            <span className="ml-1 inline-flex rounded-full bg-amber-50 px-1.5 py-0.5 text-[10px] font-medium text-amber-700 ring-1 ring-amber-200">
                              Pending Review
                            </span>
                          )}
                        </td>
                        <td className={tableCellClass + " text-xs text-gray-600 max-w-sm"}>
                          <span className="font-medium text-gray-900 block">{row.category}</span>
                          <span className="text-[11px] text-gray-500">{row.explanation}</span>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </div>
          )}

          {/* Cash Ledger Limitation Note */}
          <div className="rounded-xl border border-blue-100 bg-blue-50/50 p-4">
            <div className="flex items-start gap-2 text-xs text-blue-800">
              <Info className="h-4 w-4 shrink-0 text-blue-600 mt-0.5" />
              <div>
                <span className="font-semibold">GST Portal Limitation:</span> {data.cash_ledger_note}
              </div>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
