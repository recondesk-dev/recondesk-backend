"use client";

import { useState } from "react";
import Link from "next/link";
import {
  Check,
  Download,
  Edit3,
  FileCode2,
  RefreshCw,
  Sparkles,
  Undo2,
} from "lucide-react";

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
import {
  downloadAuditDiffCsv,
  downloadTallyRectificationXml,
  type Gstr1PatchRecord,
} from "@/lib/gstr1PatchVoucher";
import { QuickPatchModal } from "@/components/filing/QuickPatchModal";

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
  patches = [],
  onApplyPatch,
  onRemovePatch,
  onRecheckReadiness,
  filingPeriod = "",
  gstin = "",
  companyName = "",
}: {
  items: FilingPendingReviewItem[];
  byTable: Record<string, FilingPendingReviewItem[]>;
  reUploadHref?: string | null;
  patches?: Gstr1PatchRecord[];
  onApplyPatch?: (patch: Gstr1PatchRecord) => void;
  onRemovePatch?: (invNum: string) => void;
  onRecheckReadiness?: () => void;
  filingPeriod?: string;
  gstin?: string;
  companyName?: string;
}) {
  const [editingItem, setEditingItem] = useState<FilingPendingReviewItem | null>(
    null
  );

  const tables = Object.keys(byTable).sort((a, b) => a.localeCompare(b));
  const groups =
    tables.length > 0
      ? tables.map((t) => ({ table: t, rows: byTable[t] || [] }))
      : items.length > 0
        ? [{ table: "all", rows: items }]
        : [];

  const aggregateBuckets = items.filter(
    (i) =>
      i.reason === "b2cs_net_negative_bucket" ||
      i.decision_needed === "net_negative_adjustment"
  );
  const individualRows = items.filter(
    (i) =>
      !(
        i.reason === "b2cs_net_negative_bucket" ||
        i.decision_needed === "net_negative_adjustment"
      )
  );

  const findActivePatch = (ctx: Record<string, unknown>) => {
    const rNum = ctx.row_number != null ? Number(ctx.row_number) : undefined;
    const invNum = String(
      ctx.invoice_number_raw || ctx.invoice_number || ""
    ).trim();
    return patches.find(
      (p) =>
        (rNum != null && p.row_number != null
          ? Number(p.row_number) === rNum
          : false) ||
        (p.invoice_number && p.invoice_number.trim() === invNum)
    );
  };

  return (
    <section
      className={sectionContainerClass}
      aria-label="Pending review queue"
    >
      <div className="flex flex-col gap-2 sm:flex-row sm:items-center sm:justify-between">
        <SectionHeader title="Pending review" dotColor="#111111" />
        {patches.length > 0 ? (
          <span className="inline-flex items-center gap-1.5 rounded-full bg-emerald-50 px-3 py-1 text-[12px] font-semibold text-emerald-700 ring-1 ring-emerald-200">
            <Sparkles className="h-3.5 w-3.5" />
            {patches.length} Quick-Patch{patches.length === 1 ? "" : "es"} Staged
          </span>
        ) : null}
      </div>

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

      {/* Tally & ERP Sync-Back Center when patches are active */}
      {patches.length > 0 ? (
        <div className="mb-5 rounded-2xl border border-emerald-200 bg-gradient-to-br from-emerald-50/80 via-white to-teal-50/50 p-4 shadow-sm">
          <div className="flex flex-col gap-3 lg:flex-row lg:items-center lg:justify-between">
            <div>
              <div className="flex items-center gap-2">
                <span className="inline-flex items-center rounded-full bg-emerald-600 px-2.5 py-0.5 text-[11px] font-bold text-white shadow-xs">
                  {patches.length} Quick-Patch{patches.length === 1 ? "" : "es"} Active
                </span>
                <span className="text-[13px] font-bold text-emerald-950">
                  Tally & ERP Rectification Sync-Back
                </span>
              </div>
              <p className="mt-1 text-[12px] leading-relaxed text-emerald-800">
                These in-memory corrections unblock GSTR-1 Save and JSON export.
                To keep your client&apos;s accounting books 100% synchronized with the portal filing, download the Tally alteration voucher or ERP audit spreadsheet below.
              </p>
            </div>
            <div className="flex flex-wrap items-center gap-2 shrink-0">
              <button
                type="button"
                onClick={() =>
                  downloadTallyRectificationXml(
                    patches,
                    filingPeriod,
                    companyName,
                    gstin
                  )
                }
                className="inline-flex items-center gap-1.5 rounded-full bg-white px-3.5 py-1.5 text-[12px] font-semibold text-emerald-900 shadow-sm ring-1 ring-emerald-300 transition hover:bg-emerald-50"
              >
                <FileCode2 className="h-3.5 w-3.5 text-emerald-700" />
                Download Tally XML (.xml)
              </button>
              <button
                type="button"
                onClick={() => downloadAuditDiffCsv(patches, filingPeriod, gstin)}
                className="inline-flex items-center gap-1.5 rounded-full bg-white px-3.5 py-1.5 text-[12px] font-semibold text-emerald-900 shadow-sm ring-1 ring-emerald-300 transition hover:bg-emerald-50"
              >
                <Download className="h-3.5 w-3.5 text-emerald-700" />
                Audit Diff Sheet (.csv)
              </button>
              {onRecheckReadiness ? (
                <button
                  type="button"
                  onClick={onRecheckReadiness}
                  className="inline-flex items-center gap-1.5 rounded-full bg-emerald-700 px-3.5 py-1.5 text-[12px] font-semibold text-white shadow-sm transition hover:bg-emerald-800"
                >
                  <RefreshCw className="h-3.5 w-3.5" />
                  Apply & Re-check
                </button>
              ) : null}
            </div>
          </div>

          {/* Active staged patches chips */}
          <div className="mt-3 flex flex-wrap items-center gap-2 border-t border-emerald-200/60 pt-3">
            <span className="text-[11px] font-semibold text-emerald-900">
              Active Staged Corrections:
            </span>
            {patches.map((p) => (
              <div
                key={`${p.invoice_number}-${p.field_name}`}
                className="inline-flex items-center gap-1.5 rounded-full border border-emerald-200 bg-white px-2.5 py-1 text-[11px] text-emerald-900 shadow-2xs"
              >
                <span>
                  Inv <strong>{p.invoice_number}</strong>: {p.field_name} &rarr;{" "}
                  <span className="font-semibold text-emerald-700">
                    {p.patch_data.invoice_type || p.patched_value}
                  </span>
                </span>
                {onRemovePatch ? (
                  <button
                    type="button"
                    onClick={() => onRemovePatch(p.invoice_number)}
                    title="Revert this patch"
                    className="ml-1 text-gray-400 hover:text-red-600 transition"
                  >
                    <Undo2 className="h-3 w-3" />
                  </button>
                ) : null}
              </div>
            ))}
          </div>
        </div>
      ) : null}

      <div className="mb-4 rounded-xl bg-[#F7F7F8] px-4 py-3 text-[13px] text-gray-700">
        <p className="font-semibold text-[var(--ink)]">
          How to resolve pending rows
        </p>
        <p className="mt-1 leading-relaxed text-gray-600">
          <strong className="text-[var(--ink)]">Option 1 (Fastest):</strong> Click{" "}
          <span className="font-semibold text-blue-700">Quick-Patch</span> on any row below to correct GSTIN typos, set Place of Supply, or reclassify invoices in-memory. Download the Tally XML above afterwards to sync changes back to books.
        </p>
        <p className="mt-1 leading-relaxed text-gray-600">
          <strong className="text-[var(--ink)]">Option 2 (Source Register):</strong> Fix ambiguous rows directly in your accounting software / Excel register, then re-upload.
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
                      <th className="px-3 py-2.5 text-right text-[11px] font-semibold uppercase tracking-wide text-gray-400">
                        Action
                      </th>
                    </tr>
                  </thead>
                  <tbody>
                    {rows.map((row, i) => {
                      const ctx = row.context || {};
                      const isNetNegativeBucket =
                        row.reason === "b2cs_net_negative_bucket" ||
                        row.decision_needed === "net_negative_adjustment";

                      const rawInvNum = ctxStr(ctx, "invoice_number_raw") !== "—"
                        ? ctxStr(ctx, "invoice_number_raw")
                        : ctxStr(ctx, "invoice_number");

                      const inv = isNetNegativeBucket
                        ? `B2CS Net (${ctxStr(ctx, "place_of_supply") || ctxStr(ctx, "pos")} @ ${ctxStr(ctx, "tax_rate") || ctxStr(ctx, "rt")}%)`
                        : rawInvNum;

                      const rowNum = isNetNegativeBucket
                        ? "Aggregate"
                        : ctxStr(ctx, "row_number");

                      const ctin = isNetNegativeBucket
                        ? "Unregistered (B2C)"
                        : ctxStr(ctx, "gstin");

                      const activePatch = !isNetNegativeBucket
                        ? findActivePatch(ctx)
                        : undefined;

                      return (
                        <tr
                          key={`${row.reason}-${inv}-${i}`}
                          className={`border-t border-[#F0F0F0] ${activePatch ? "bg-emerald-50/30" : ""}`}
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
                            {activePatch?.patch_data.gstin ? (
                              <span className="font-semibold text-emerald-800">
                                {activePatch.patch_data.gstin}
                              </span>
                            ) : (
                              ctin
                            )}
                          </td>
                          <td className="px-3 py-2.5 text-[13px] tabular-nums text-gray-700">
                            {ctxPaiseInr(ctx, "taxable_amount_paise")}
                          </td>
                          <td className="px-3 py-2.5">
                            {activePatch ? (
                              <span className="inline-flex items-center gap-1 rounded-full bg-emerald-100 px-2 py-0.5 text-[11px] font-bold text-emerald-800">
                                <Check className="h-3 w-3" />
                                Patched: {activePatch.patch_data.invoice_type || activePatch.patched_value}
                              </span>
                            ) : (
                              <>
                                <span className="inline-flex rounded-full bg-[#F5F5F6] px-2.5 py-0.5 text-[11px] font-semibold text-gray-700">
                                  {decisionNeededLabel(row.decision_needed)}
                                </span>
                                {row.proposed_inv_typ ? (
                                  <span className="mt-1 block text-[11px] text-gray-500">
                                    Proposed: {row.proposed_inv_typ}
                                  </span>
                                ) : null}
                              </>
                            )}
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
                          <td className="px-3 py-2.5 text-right whitespace-nowrap">
                            {isNetNegativeBucket ? (
                              <span className="text-[11px] italic text-gray-400">
                                Rule 37A carry-forward
                              </span>
                            ) : activePatch ? (
                              <div className="flex items-center justify-end gap-1.5">
                                <button
                                  type="button"
                                  onClick={() => setEditingItem(row)}
                                  className="rounded-full bg-blue-50 px-2.5 py-1 text-[11px] font-semibold text-blue-700 hover:bg-blue-100"
                                >
                                  Edit
                                </button>
                                {onRemovePatch ? (
                                  <button
                                    type="button"
                                    onClick={() => onRemovePatch(rawInvNum)}
                                    title="Revert patch"
                                    className="rounded-full p-1 text-gray-400 hover:bg-red-50 hover:text-red-600"
                                  >
                                    <Undo2 className="h-3.5 w-3.5" />
                                  </button>
                                ) : null}
                              </div>
                            ) : (
                              <button
                                type="button"
                                onClick={() => setEditingItem(row)}
                                className="inline-flex items-center gap-1 rounded-full border border-gray-200 bg-white px-2.5 py-1 text-[11px] font-semibold text-gray-700 shadow-2xs transition hover:border-blue-300 hover:bg-blue-50/50 hover:text-blue-700"
                              >
                                <Edit3 className="h-3 w-3 text-blue-600" />
                                Quick-Patch
                              </button>
                            )}
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

      {/* Quick-Patch Modal */}
      {editingItem ? (
        <QuickPatchModal
          isOpen={!!editingItem}
          onClose={() => setEditingItem(null)}
          item={editingItem}
          existingPatch={findActivePatch((editingItem.context || {}) as Record<string, unknown>)}
          onApplyPatch={(patch) => {
            onApplyPatch?.(patch);
          }}
        />
      ) : null}
    </section>
  );
}
