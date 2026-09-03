"use client";

import Link from "next/link";

import type { FilingPendingReviewItem } from "@/lib/api";
import { formatINR } from "@/lib/format";
import {
  SectionHeader,
  sectionContainerClass,
  tableClass,
  tableHeadClass,
  tableWrapClass,
} from "@/components/reconcile/ResultsUi";
import {
  decisionNeededLabel,
  tableLabel,
} from "@/components/filing/filingHelpers";

function ctxStr(ctx: Record<string, unknown>, key: string): string {
  const v = ctx[key];
  if (v == null || v === "") return "—";
  return String(v);
}

function ctxPaiseInr(ctx: Record<string, unknown>, key: string): string {
  const v = ctx[key];
  if (v == null || v === "") return "—";
  const n = Number(v);
  if (!Number.isFinite(n)) return "—";
  return formatINR(n / 100);
}

export function PendingReviewQueue({
  items,
  byTable,
  reUploadHref,
}: {
  items: FilingPendingReviewItem[];
  byTable: Record<string, FilingPendingReviewItem[]>;
  reUploadHref?: string | null;
}) {
  const tables = Object.keys(byTable).sort((a, b) => a.localeCompare(b));
  const groups =
    tables.length > 0
      ? tables.map((t) => ({ table: t, rows: byTable[t] || [] }))
      : items.length > 0
        ? [{ table: "all", rows: items }]
        : [];

  const aggregateBuckets = items.filter(
    (i) => i.reason === "b2cs_net_negative_bucket" || i.decision_needed === "net_negative_adjustment"
  );
  const individualRows = items.filter(
    (i) => !(i.reason === "b2cs_net_negative_bucket" || i.decision_needed === "net_negative_adjustment")
  );

  return (
    <section
      className={sectionContainerClass}
      aria-label="Pending review queue"
    >
      <SectionHeader title="Pending review" dotColor="#111111" />
      <p className="mb-3 text-[13px] text-gray-500">
        {aggregateBuckets.length > 0 && individualRows.length > 0 ? (
          <>
            <span className="font-semibold tabular-nums text-[var(--ink)]">
              {individualRows.length}
            </span>{" "}
            individual row{individualRows.length === 1 ? "" : "s"} +{" "}
            <span className="font-semibold tabular-nums text-[var(--ink)]">
              {aggregateBuckets.length}
            </span>{" "}
            net negative aggregate bucket{aggregateBuckets.length === 1 ? "" : "s"} held out of Save.
          </>
        ) : aggregateBuckets.length > 0 ? (
          <>
            <span className="font-semibold tabular-nums text-[var(--ink)]">
              {aggregateBuckets.length}
            </span>{" "}
            net negative aggregate bucket{aggregateBuckets.length === 1 ? "" : "s"} held out of Save.
          </>
        ) : (
          <>
            <span className="font-semibold tabular-nums text-[var(--ink)]">
              {items.length}
            </span>{" "}
            row{items.length === 1 ? "" : "s"} held out of Save until types are
            clarified in the Sales Register.
          </>
        )}
      </p>
      <div className="mb-4 rounded-xl bg-[#F7F7F8] px-4 py-3 text-[13px] text-gray-700">
        <p className="font-medium text-[var(--ink)]">
          How to resolve these (v1)
        </p>
        <p className="mt-1 leading-relaxed">
          This queue is read-only. Correct ambiguous invoice / note / export
          types in your Sales Register (or Tally export), then re-upload that
          file and re-run readiness here. There is no in-app inv_typ editor yet
          — fixing the source register is the intended workflow.
        </p>
        {reUploadHref ? (
          <p className="mt-2">
            <Link
              href={reUploadHref}
              className="text-[13px] font-semibold text-[var(--ink)] underline-offset-2 hover:underline"
            >
              Re-upload Sales Register on this page ↑
            </Link>
          </p>
        ) : (
          <p className="mt-2 text-[12px] text-gray-500">
            Use the Sales Register upload above, then click Check readiness
            again.
          </p>
        )}
        {aggregateBuckets.length > 0 ? (
          <div className="mt-3 rounded-lg border border-amber-200/80 bg-amber-50/60 p-3 text-[12px] text-amber-900">
            <p className="font-semibold">Net negative B2CS buckets ({aggregateBuckets.length})</p>
            <p className="mt-1 leading-relaxed">
              Credit notes/returns exceed outward B2C sales for these state + rate combinations in this period. The GST portal does not allow negative taxable values in Table 7 (B2CS). Under GST rules, this net credit liability must be carried forward to offset future outward B2C liabilities in subsequent tax periods. This cannot be resolved by re-uploading the same register.
            </p>
          </div>
        ) : null}
      </div>

      {items.length === 0 ? (
        <p className="text-[13px] text-gray-500">
          No rows need a type decision — clear invoices are included in Save.
        </p>
      ) : (
        <div className="space-y-6">
          {groups.map(({ table, rows }) => (
            <div key={table}>
              <h3 className="mb-2 text-[13px] font-semibold text-[var(--ink)]">
                {table === "all" ? "All tables" : tableLabel(table)}
                <span className="ml-2 font-medium text-gray-400">
                  ({rows.length})
                </span>
              </h3>
              <div className={tableWrapClass}>
                <table className={tableClass}>
                  <thead>
                    <tr className={tableHeadClass}>
                      <th className="px-3 py-2.5 text-[11px] font-semibold uppercase tracking-wide text-gray-400">
                        Row #
                      </th>
                      <th className="px-3 py-2.5 text-[11px] font-semibold uppercase tracking-wide text-gray-400">
                        Invoice
                      </th>
                      <th className="px-3 py-2.5 text-[11px] font-semibold uppercase tracking-wide text-gray-400">
                        Date
                      </th>
                      <th className="px-3 py-2.5 text-[11px] font-semibold uppercase tracking-wide text-gray-400">
                        CTIN
                      </th>
                      <th className="px-3 py-2.5 text-[11px] font-semibold uppercase tracking-wide text-gray-400">
                        Taxable
                      </th>
                      <th className="px-3 py-2.5 text-[11px] font-semibold uppercase tracking-wide text-gray-400">
                        Decision
                      </th>
                      <th className="px-3 py-2.5 text-[11px] font-semibold uppercase tracking-wide text-gray-400">
                        Source type
                      </th>
                      <th className="px-3 py-2.5 text-[11px] font-semibold uppercase tracking-wide text-gray-400">
                        Why held
                      </th>
                    </tr>
                  </thead>
                  <tbody>
                    {rows.map((row, i) => {
                      const ctx = row.context || {};
                      const isNetNegativeBucket =
                        row.reason === "b2cs_net_negative_bucket" ||
                        row.decision_needed === "net_negative_adjustment";

                      const inv = isNetNegativeBucket
                        ? `B2CS Net (${ctxStr(ctx, "place_of_supply") || ctxStr(ctx, "pos")} @ ${ctxStr(ctx, "tax_rate") || ctxStr(ctx, "rt")}%)`
                        : ctxStr(ctx, "invoice_number_raw") !== "—"
                        ? ctxStr(ctx, "invoice_number_raw")
                        : ctxStr(ctx, "invoice_number");

                      const rowNum = isNetNegativeBucket
                        ? "Aggregate"
                        : ctxStr(ctx, "row_number");

                      const ctin = isNetNegativeBucket
                        ? "Unregistered (B2C)"
                        : ctxStr(ctx, "gstin");

                      return (
                        <tr
                          key={`${row.reason}-${inv}-${i}`}
                          className="border-t border-[#F0F0F0]"
                        >
                          <td className="px-3 py-2.5 text-[12px] tabular-nums text-gray-600">
                            {rowNum}
                          </td>
                          <td className="px-3 py-2.5 text-[13px] font-medium text-[var(--ink)]">
                            {inv}
                          </td>
                          <td className="px-3 py-2.5 text-[13px] tabular-nums text-gray-700">
                            {isNetNegativeBucket ? "—" : ctxStr(ctx, "invoice_date")}
                          </td>
                          <td className="px-3 py-2.5 font-mono text-[12px] text-gray-700">
                            {ctin}
                          </td>
                          <td className="px-3 py-2.5 text-[13px] tabular-nums text-gray-700">
                            {ctxPaiseInr(ctx, "taxable_amount_paise")}
                          </td>
                          <td className="px-3 py-2.5">
                            <span className="inline-flex rounded-full bg-[#F5F5F6] px-2.5 py-0.5 text-[11px] font-semibold text-gray-700">
                              {decisionNeededLabel(row.decision_needed)}
                            </span>
                            {row.proposed_inv_typ ? (
                              <span className="mt-1 block text-[11px] text-gray-500">
                                Proposed: {row.proposed_inv_typ}
                              </span>
                            ) : null}
                          </td>
                          <td className="px-3 py-2.5 text-[12px] text-gray-600">
                            {isNetNegativeBucket
                              ? ctxStr(ctx, "sply_ty") !== "—"
                                ? `${ctxStr(ctx, "sply_ty")} (B2CS Net)`
                                : "B2CS Aggregate"
                              : ctxStr(ctx, "invoice_type_raw") !== "—"
                              ? ctxStr(ctx, "invoice_type_raw")
                              : ctxStr(ctx, "invoice_type")}
                            {ctxStr(ctx, "export_type_raw") !== "—" ? (
                              <span className="mt-0.5 block text-gray-400">
                                export: {ctxStr(ctx, "export_type_raw")}
                              </span>
                            ) : null}
                          </td>
                          <td className="max-w-[220px] px-3 py-2.5 text-[12px] text-gray-600">
                            {row.reason}
                          </td>
                        </tr>
                      );
                    })}
                  </tbody>
                </table>
              </div>
            </div>
          ))}
        </div>
      )}
    </section>
  );
}
