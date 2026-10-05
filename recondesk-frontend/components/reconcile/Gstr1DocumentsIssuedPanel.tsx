"use client";

import type { Gstr1DocumentsIssued } from "@/lib/gstr1Reconcile";
import {
  SectionHeader,
  StatCard,
  statCardsGridClass,
} from "./ResultsUi";

function CancelCell({ value }: { value: number | null | undefined }) {
  if (value == null) {
    return (
      <span className="text-[12px] text-[#968BA2]" title="Not determinable from Sales Register">
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
    <section className="box-border w-full max-w-full rounded-[14px] border border-[#E8E0F1] bg-white p-6 shadow-xs">
      <SectionHeader
        title="Table 13 – Documents Issued Summary"
        dotColor="#78608F"
        actions={
          <div className="flex flex-wrap gap-2">
            {!data.cancellations_determinable ? (
              <span className="inline-flex items-center gap-1.5 rounded-full bg-[#FFF5DD] px-3 py-1 text-xs font-semibold text-[#97621C] border border-[#FDE7B2]">
                Cancellations unknown
              </span>
            ) : (
              <span className="inline-flex items-center gap-1.5 rounded-full bg-[#E7F8EE] px-3 py-1 text-xs font-semibold text-[#237B51] border border-[#D1F2DD]">
                Cancellations tracked
              </span>
            )}
            {!data.gstr1_doc_issue_present ? (
              <span className="inline-flex items-center gap-1.5 rounded-full bg-[#F0EAF7] px-3 py-1 text-xs font-semibold text-[#554260] border border-[#E8E0F1]">
                No GSTR-1 doc_issue section
              </span>
            ) : null}
          </div>
        }
      />
      <p className="mt-1 text-xs text-[#756184]">
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
        <div className="mt-6 overflow-x-auto rounded-xl border border-[#E8E0F1] bg-white">
          <table className="min-w-full text-left">
            <thead>
              <tr className="border-b border-[#EEE8F4] bg-[#FAF9FC] text-[11px] font-bold uppercase tracking-[0.5px] text-[#968BA2]">
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
                  className="border-b border-[#EEE8F4] last:border-b-0 hover:bg-[#FCFBFE] transition-colors"
                >
                  <td className="px-4 py-3 text-[13px] font-medium text-[#342B40]">
                    {row.document_type_label || row.document_type}
                  </td>
                  <td className="px-4 py-3 text-right text-[13px] tabular-nums text-[#594C66]">
                    {(row.series_count ?? 0).toLocaleString("en-IN")}
                  </td>
                  <td className="px-4 py-3 text-right text-[13px] tabular-nums text-[#594C66]">
                    {(row.total_issued ?? 0).toLocaleString("en-IN")}
                  </td>
                  <td className="px-4 py-3 text-right text-[13px] text-[#594C66]">
                    <CancelCell value={row.cancelled} />
                  </td>
                  <td className="px-4 py-3 text-right text-[13px] font-semibold tabular-nums text-[#342B40]">
                    {(row.net_issued ?? 0).toLocaleString("en-IN")}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ) : null}

      <div className="mt-6">
        <h3 className="mb-3 text-sm font-bold tracking-tight text-[#342B40]">
          Series detail
        </h3>
        {series.length === 0 ? (
          <p className="text-xs text-[#756184]">
            No document series could be derived from the Sales Register.
          </p>
        ) : (
          <div className="overflow-x-auto rounded-xl border border-[#E8E0F1] bg-white">
            <table className="min-w-full text-left">
              <thead>
                <tr className="border-b border-[#EEE8F4] bg-[#FAF9FC] text-[11px] font-bold uppercase tracking-[0.5px] text-[#968BA2]">
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
                    className="border-b border-[#EEE8F4] last:border-b-0 hover:bg-[#FCFBFE] transition-colors"
                  >
                    <td className="px-4 py-3 text-[13px] text-[#342B40]">
                      {row.document_type_label || row.document_type}
                      {!row.span_bounded ? (
                        <span
                          className="ml-2 text-[11px] font-semibold text-[#97621C]"
                          title="Numeric span too large for range checks"
                        >
                          span capped
                        </span>
                      ) : null}
                    </td>
                    <td className="px-4 py-3 font-mono text-xs text-[#594C66]">
                      {row.series_prefix || "(numeric)"}
                    </td>
                    <td className="px-4 py-3 font-mono text-xs text-[#342B40]">
                      {row.opening_number}
                    </td>
                    <td className="px-4 py-3 font-mono text-xs text-[#342B40]">
                      {row.closing_number}
                    </td>
                    <td className="px-4 py-3 text-right text-[13px] tabular-nums text-[#594C66]">
                      {row.total_issued.toLocaleString("en-IN")}
                    </td>
                    <td className="px-4 py-3 text-right text-[13px] text-[#594C66]">
                      <CancelCell value={row.cancelled} />
                    </td>
                    <td className="px-4 py-3 text-right text-[13px] font-semibold tabular-nums text-[#342B40]">
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
