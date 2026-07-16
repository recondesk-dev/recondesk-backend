"use client";

import type { Gstr1DocumentsIssued } from "@/lib/gstr1Reconcile";
import {
  SectionHeader,
  sectionContainerClass,
  StatCard,
  statCardsGridClass,
} from "./ResultsUi";

function CancelCell({ value }: { value: number | null | undefined }) {
  if (value == null) {
    return (
      <span className="text-[12px] text-gray-400" title="Not determinable from Sales Register">
        —
      </span>
    );
  }
  return <span className="tabular-nums">{value.toLocaleString("en-IN")}</span>;
}

export function Gstr1DocumentsIssuedPanel({
  documentsIssued,
}: {
  documentsIssued?: Gstr1DocumentsIssued | null;
}) {
  const data = documentsIssued || {};
  const series = data.series || [];
  const byType = data.by_document_type || {};
  const typeRows = Object.values(byType);

  return (
    <section className={sectionContainerClass}>
      <SectionHeader
        title="Table 13 – Documents Issued Summary"
        dotColor="#6B7280"
        actions={
          <div className="flex flex-wrap gap-2">
            {!data.cancellations_determinable ? (
              <span className="inline-flex items-center gap-1.5 rounded-full bg-amber-50 px-3 py-1 text-[12px] font-semibold text-amber-800 ring-1 ring-amber-200">
                Cancellations unknown
              </span>
            ) : (
              <span className="inline-flex items-center gap-1.5 rounded-full bg-green-50 px-3 py-1 text-[12px] font-semibold text-green-700 ring-1 ring-green-200">
                Cancellations tracked
              </span>
            )}
            {!data.gstr1_doc_issue_present ? (
              <span className="inline-flex items-center gap-1.5 rounded-full bg-[#F5F5F6] px-3 py-1 text-[12px] font-medium text-gray-600">
                No GSTR-1 doc_issue section
              </span>
            ) : null}
          </div>
        }
      />
      <p className="mt-1 text-[13px] text-gray-500">
        {data.source === "gstr1"
          ? "Derived from GSTR-1 invoice rows (Sales Register empty)."
          : "Derived from Sales Register series for GSTR-1 Table 13 filing."}
      </p>

      <div className={statCardsGridClass}>
        <StatCard
          label="Series"
          value={(data.total_series ?? series.length).toLocaleString("en-IN")}
          emphasis="secondary"
        />
        <StatCard
          label="Documents issued"
          value={(data.total_documents_issued ?? 0).toLocaleString("en-IN")}
        />
        <StatCard
          label="Document types"
          value={typeRows.length.toLocaleString("en-IN")}
          emphasis="secondary"
        />
      </div>

      {typeRows.length > 0 ? (
        <div className="mt-6 overflow-x-auto rounded-2xl border border-[#F0F0F0] bg-white">
          <table className="min-w-full text-left">
            <thead>
              <tr className="border-b border-[#F0F0F0] bg-[#FAFAFA] text-[11px] font-semibold uppercase tracking-wider text-gray-400">
                <th className="px-4 py-3">Document type</th>
                <th className="px-4 py-3 text-right">Series</th>
                <th className="px-4 py-3 text-right">Issued</th>
                <th className="px-4 py-3 text-right">Cancelled</th>
                <th className="px-4 py-3 text-right">Net issued</th>
              </tr>
            </thead>
            <tbody>
              {typeRows.map((row) => (
                <tr
                  key={row.document_type}
                  className="border-b border-[#F0F0F0] last:border-b-0"
                >
                  <td className="px-4 py-3 text-[13px] font-medium text-[var(--ink)]">
                    {row.document_type_label || row.document_type}
                  </td>
                  <td className="px-4 py-3 text-right text-[13px] tabular-nums text-gray-700">
                    {(row.series_count ?? 0).toLocaleString("en-IN")}
                  </td>
                  <td className="px-4 py-3 text-right text-[13px] tabular-nums text-gray-700">
                    {(row.total_issued ?? 0).toLocaleString("en-IN")}
                  </td>
                  <td className="px-4 py-3 text-right text-[13px] text-gray-700">
                    <CancelCell value={row.cancelled} />
                  </td>
                  <td className="px-4 py-3 text-right text-[13px] font-semibold tabular-nums text-[var(--ink)]">
                    {(row.net_issued ?? 0).toLocaleString("en-IN")}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ) : null}

      <div className="mt-6">
        <h3 className="mb-3 text-[14px] font-semibold tracking-tight text-[var(--ink)]">
          Series detail
        </h3>
        {series.length === 0 ? (
          <p className="text-[13px] text-gray-500">
            No document series could be derived from the Sales Register.
          </p>
        ) : (
          <div className="overflow-x-auto rounded-2xl border border-[#F0F0F0] bg-white">
            <table className="min-w-full text-left">
              <thead>
                <tr className="border-b border-[#F0F0F0] bg-[#FAFAFA] text-[11px] font-semibold uppercase tracking-wider text-gray-400">
                  <th className="px-4 py-3">Type</th>
                  <th className="px-4 py-3">Prefix</th>
                  <th className="px-4 py-3">Opening</th>
                  <th className="px-4 py-3">Closing</th>
                  <th className="px-4 py-3 text-right">Issued</th>
                  <th className="px-4 py-3 text-right">Cancelled</th>
                  <th className="px-4 py-3 text-right">Net</th>
                </tr>
              </thead>
              <tbody>
                {series.map((row, i) => (
                  <tr
                    key={`${row.document_type}-${row.series_prefix}-${i}`}
                    className="border-b border-[#F0F0F0] last:border-b-0"
                  >
                    <td className="px-4 py-3 text-[13px] text-gray-700">
                      {row.document_type_label || row.document_type}
                      {!row.span_bounded ? (
                        <span
                          className="ml-2 text-[11px] text-amber-700"
                          title="Numeric span too large for range checks"
                        >
                          span capped
                        </span>
                      ) : null}
                    </td>
                    <td className="px-4 py-3 font-mono text-[12px] text-gray-600">
                      {row.series_prefix || "(numeric)"}
                    </td>
                    <td className="px-4 py-3 font-mono text-[12px] text-[var(--ink)]">
                      {row.opening_number}
                    </td>
                    <td className="px-4 py-3 font-mono text-[12px] text-[var(--ink)]">
                      {row.closing_number}
                    </td>
                    <td className="px-4 py-3 text-right text-[13px] tabular-nums text-gray-700">
                      {row.total_issued.toLocaleString("en-IN")}
                    </td>
                    <td className="px-4 py-3 text-right text-[13px] text-gray-700">
                      <CancelCell value={row.cancelled} />
                    </td>
                    <td className="px-4 py-3 text-right text-[13px] font-semibold tabular-nums text-[var(--ink)]">
                      {row.net_issued.toLocaleString("en-IN")}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>
    </section>
  );
}
