"use client";

import {
  Check,
  FileSpreadsheet,
  FileText,
  Loader2,
} from "lucide-react";
import { useMemo, useState } from "react";

import {
  DecisionInvoiceCard,
  DecisionInvoiceList,
} from "@/components/reconcile/DecisionInvoiceCard";
import { Gstr1TieOutPanel } from "@/components/reconcile/Gstr1TieOutPanel";
import {
  EmptyTableState,
  pageContentClass,
  ResultsBucketTabs,
  resultsSummaryGridClass,
  SALES_RESULTS_BUCKET_TABS,
  sectionContainerClass,
  StatCard,
  type ResultsBucketTabId,
} from "@/components/reconcile/ResultsUi";
import {
  countMismatchesByType,
  filterReviewRequired,
  mismatchTypeShort,
  recordAmountRupees,
  recordGstin,
  recordInvoiceNumber,
  type Gstr1MatchedRow,
  type Gstr1ReconcileResult,
  type Gstr1UnmatchedRow,
} from "@/lib/gstr1Reconcile";
import {
  downloadGstr1ExcelReport,
  downloadGstr1PdfReport,
} from "@/lib/gstr1ReconcileExport";

function SeverityPill({ severity }: { severity?: string | null }) {
  const s = String(severity || "").toLowerCase();
  const tone =
    s === "critical"
      ? "bg-red-50 text-red-700"
      : s === "high"
        ? "bg-amber-50 text-amber-800"
        : s === "medium"
          ? "bg-[#F0F0F0] text-gray-600"
          : "bg-[#F0F0F0] text-gray-500";
  return (
    <span
      className={`inline-flex rounded-full px-2.5 py-0.5 text-[11px] font-medium capitalize ${tone}`}
    >
      {severity || "—"}
    </span>
  );
}

function TypePill({ type }: { type?: string }) {
  return (
    <span className="inline-flex rounded-full bg-[var(--ink)] px-2.5 py-0.5 text-[11px] font-semibold text-white">
      {mismatchTypeShort(type)}
    </span>
  );
}

function gstinDisplay(raw: string): string {
  return raw.trim() || "Unregistered B2C";
}

function MatchedCards({
  rows,
  emptyTitle,
  emptyDescription,
}: {
  rows: Gstr1MatchedRow[];
  emptyTitle: string;
  emptyDescription?: string;
}) {
  if (rows.length === 0) {
    return (
      <EmptyTableState title={emptyTitle} description={emptyDescription} />
    );
  }
  return (
    <DecisionInvoiceList>
      {rows.map((row, i) => {
        const sr = row.sr_record || {};
        return (
          <DecisionInvoiceCard
            key={`${recordInvoiceNumber(sr)}-${i}`}
            index={i + 1}
            gstin={gstinDisplay(recordGstin(sr))}
            invoiceNumber={recordInvoiceNumber(sr)}
            invoiceDate={String(sr.invoice_date || "—")}
            amount={recordAmountRupees(sr)}
            amountCaption="Taxable"
            what={row.decision_what || row.review_reason || "Matched"}
            why={
              row.decision_why ||
              (row.discrepancies?.length
                ? row.discrepancies.join(" · ")
                : "Sales Register and GSTR-1 align within matching rules.")
            }
            next={
              row.decision_next ||
              (row.requires_human_review
                ? "Verify invoice details before filing."
                : "No action required.")
            }
            status={
              <span className="inline-flex rounded-full bg-[#F5F5F6] px-2.5 py-0.5 text-[11px] font-medium text-gray-600">
                L{row.match_level ?? "—"} · {row.confidence ?? "—"}%
              </span>
            }
            meta={
              row.decision_confidence ? (
                <span className="text-[11px] text-gray-400">
                  {row.decision_confidence}
                </span>
              ) : null
            }
          />
        );
      })}
    </DecisionInvoiceList>
  );
}

function UnmatchedCards({
  rows,
  emptyTitle,
}: {
  rows: Gstr1UnmatchedRow[];
  emptyTitle: string;
}) {
  if (rows.length === 0) {
    return <EmptyTableState title={emptyTitle} />;
  }
  return (
    <DecisionInvoiceList>
      {rows.map((row, i) => {
        const rec = row.record || {};
        return (
          <DecisionInvoiceCard
            key={`${recordInvoiceNumber(rec)}-${i}`}
            index={i + 1}
            gstin={gstinDisplay(
              recordGstin(rec) || String(row.recipient_gstin || "")
            )}
            invoiceNumber={recordInvoiceNumber(rec)}
            invoiceDate={String(rec.invoice_date || "—")}
            amount={recordAmountRupees(rec)}
            amountCaption="Taxable"
            what={row.decision_what}
            why={row.decision_why}
            next={row.decision_next}
            status={<SeverityPill severity={row.mismatch_severity} />}
            impact={<TypePill type={row.mismatch_type} />}
          />
        );
      })}
    </DecisionInvoiceList>
  );
}

export function Gstr1ResultsView({
  result,
  onRunAgain,
}: {
  result: Gstr1ReconcileResult;
  onRunAgain?: () => void;
}) {
  const [tab, setTab] = useState<ResultsBucketTabId>("matched");
  const [excelBusy, setExcelBusy] = useState(false);
  const [pdfBusy, setPdfBusy] = useState(false);

  const reviewRows = useMemo(
    () => filterReviewRequired(result.matched || []),
    [result.matched]
  );
  const mismatchCounts = useMemo(
    () => countMismatchesByType(result.mismatches || []),
    [result.mismatches]
  );

  const summary = result.summary;
  const matchRate =
    summary.gstr1_total_records > 0
      ? Math.round(
          (summary.matched_count / summary.gstr1_total_records) * 1000
        ) / 10
      : 0;

  const periodLabel =
    result.meta?.filing_period ||
    result.tie_out?.ret_period ||
    result.parse_diagnostics?.gstr1?.filing_period ||
    "—";

  const handleExcel = () => {
    setExcelBusy(true);
    try {
      downloadGstr1ExcelReport(result);
    } finally {
      setExcelBusy(false);
    }
  };

  const handlePdf = async () => {
    setPdfBusy(true);
    try {
      await downloadGstr1PdfReport(result);
    } finally {
      setPdfBusy(false);
    }
  };

  return (
    <div className="min-h-screen w-full min-w-0 pb-32">
      {/* Sticky header + KPIs */}
      <div className="sticky top-0 z-30 border-b border-[#F0F0F0]/80 bg-white/90 px-8 py-5 backdrop-blur-xl">
        <div className="flex flex-wrap items-start justify-between gap-4">
          <div className="min-w-0">
            <p className="text-[11px] font-medium uppercase tracking-widest text-gray-400">
              Sales Reconciliation · GSTR-1 Check
            </p>
            <h1 className="mt-1 text-xl font-semibold tracking-tight text-[var(--ink)]">
              Period {periodLabel}
            </h1>
            <p className="mt-1 text-[13px] text-gray-500">
              {[
                result.meta?.sales_register_filename,
                result.meta?.gstr1_filename,
                result.meta?.gstr3b_filename,
              ]
                .filter(Boolean)
                .join(" · ") || "Sales Register ↔ GSTR-1 ↔ GSTR-3B"}
            </p>
            {!summary.tie_out_clean ? (
              <span className="mt-2 inline-flex rounded-full bg-amber-50 px-2.5 py-0.5 text-[11px] font-medium text-amber-800 ring-1 ring-amber-200">
                GSTR-1 vs 3B variances need review
              </span>
            ) : (
              <span className="mt-2 inline-flex rounded-full bg-[var(--ink)] px-2.5 py-0.5 text-[11px] font-medium text-white">
                Tie-out clean
              </span>
            )}
          </div>

          <div className="flex shrink-0 items-center gap-2">
            <button
              type="button"
              disabled={excelBusy}
              className="inline-flex h-9 items-center gap-2 rounded-full bg-[#F5F5F6] px-4 text-[13px] font-semibold text-gray-700 transition-colors hover:bg-gray-200/70 disabled:opacity-50"
              onClick={handleExcel}
            >
              {excelBusy ? (
                <Loader2 className="h-4 w-4 animate-spin" />
              ) : (
                <FileSpreadsheet className="h-4 w-4 text-gray-500" />
              )}
              Excel
            </button>
            <button
              type="button"
              disabled={pdfBusy}
              className="inline-flex h-9 items-center gap-2 rounded-full bg-[#F5F5F6] px-4 text-[13px] font-semibold text-gray-700 transition-colors hover:bg-gray-200/70 disabled:opacity-50"
              onClick={() => void handlePdf()}
            >
              {pdfBusy ? (
                <Loader2 className="h-4 w-4 animate-spin" />
              ) : (
                <FileText className="h-4 w-4 text-gray-500" />
              )}
              PDF
            </button>
          </div>
        </div>

        <div className={resultsSummaryGridClass}>
          <StatCard
            label="Sales Register"
            value={summary.sr_total_records.toLocaleString("en-IN")}
            emphasis="secondary"
          />
          <StatCard
            label="Matched"
            accent="matched"
            value={summary.matched_count.toLocaleString("en-IN")}
            subtext={`${matchRate}% of GSTR-1`}
          />
          <StatCard
            label="Review Required"
            accent="review_required"
            value={reviewRows.length.toLocaleString("en-IN")}
            subtext="Needs verification"
            emphasis="attention"
          />
          <StatCard
            label="Missing in GSTR-1"
            accent="missed"
            emphasis="danger"
            value={summary.unmatched_sr_count.toLocaleString("en-IN")}
            subtext="Under-reporting risk"
          />
          <StatCard
            label="Extra / Mismatches"
            accent="risk"
            emphasis="danger"
            value={(
              summary.unmatched_gstr1_count + summary.mismatch_count
            ).toLocaleString("en-IN")}
            subtext={`${summary.tie_out_variance_count} tie-out variance${summary.tie_out_variance_count === 1 ? "" : "s"}`}
          />
        </div>

        <div className="mt-4 flex w-full items-center gap-3">
          <div className="min-w-0 flex-1 overflow-hidden">
            <div className="h-1.5 w-full overflow-hidden rounded-full bg-white">
              <div
                className="h-1.5 max-w-full rounded-full bg-[var(--ink)] transition-all duration-150"
                style={{ width: `${Math.min(100, Math.max(0, matchRate))}%` }}
              />
            </div>
          </div>
          <p className="shrink-0 whitespace-nowrap text-[11px] text-gray-400">
            Match rate
          </p>
          <span className="inline-flex items-center rounded-full bg-[var(--ink)] px-2.5 py-0.5 text-[11px] font-medium text-white">
            {matchRate}%
          </span>
        </div>
      </div>

      <div className={pageContentClass}>
        {/* Compact mismatch-type strip */}
        {Object.keys(mismatchCounts).length > 0 ? (
          <div className="flex flex-wrap gap-2">
            {(["G1M1", "G1M2", "G1M3", "G1M4", "G1M5", "G1M6"] as const).map(
              (code) =>
                mismatchCounts[code] ? (
                  <span
                    key={code}
                    className="inline-flex items-center gap-1.5 rounded-full bg-white px-3 py-1.5 text-[12px] font-medium text-gray-600 shadow-[var(--shadow-soft)]"
                  >
                    <span className="font-semibold text-[var(--ink)]">
                      {code}
                    </span>
                    {mismatchCounts[code]}
                  </span>
                ) : null
            )}
          </div>
        ) : null}

        <ResultsBucketTabs
          active={tab}
          onChange={setTab}
          tabs={SALES_RESULTS_BUCKET_TABS}
          ariaLabel="GSTR-1 sales reconciliation results"
          tabCounts={{
            matched: summary.matched_count,
            review_required: reviewRows.length,
            unmatched_sr: summary.unmatched_sr_count,
            unmatched_gstr1: summary.unmatched_gstr1_count,
            tie_out: summary.tie_out_variance_count,
            diagnostics:
              (result.parse_diagnostics?.sr?.skipped_rows || 0) +
              (result.parse_diagnostics?.gstr1?.total_skipped || 0),
          }}
          rightContent={
            <button
              type="button"
              disabled={pdfBusy}
              className="inline-flex h-9 items-center gap-2 rounded-full bg-[var(--ink)] px-4 text-[13px] font-semibold text-white transition-opacity hover:opacity-90 disabled:opacity-50"
              onClick={() => void handlePdf()}
            >
              {pdfBusy ? (
                <Loader2 className="h-4 w-4 animate-spin" />
              ) : (
                <FileText className="h-4 w-4" />
              )}
              Download Report (PDF)
            </button>
          }
        />

        {tab === "matched" && (
          <section className={sectionContainerClass}>
            <h2 className="mb-4 text-[15px] font-semibold tracking-tight text-[var(--ink)]">
              Matched{" "}
              <span className="text-gray-400">
                ({summary.matched_count.toLocaleString("en-IN")})
              </span>
            </h2>
            <MatchedCards
              rows={result.matched || []}
              emptyTitle="No matched invoices"
              emptyDescription="No Sales Register rows linked to GSTR-1 for this period."
            />
          </section>
        )}

        {tab === "review_required" && (
          <section className={sectionContainerClass}>
            <h2 className="mb-4 text-[15px] font-semibold tracking-tight text-[var(--ink)]">
              Review Required{" "}
              <span className="text-gray-400">
                ({reviewRows.length.toLocaleString("en-IN")})
              </span>
            </h2>
            <MatchedCards
              rows={reviewRows}
              emptyTitle="Nothing needs review"
              emptyDescription="All matched pairs look clean — no discrepancies or low-confidence links."
            />
          </section>
        )}

        {tab === "unmatched_sr" && (
          <section className={sectionContainerClass}>
            <h2 className="mb-4 text-[15px] font-semibold tracking-tight text-[var(--ink)]">
              Missing in GSTR-1{" "}
              <span className="text-gray-400">
                ({summary.unmatched_sr_count.toLocaleString("en-IN")})
              </span>
            </h2>
            <p className="mb-4 text-[13px] text-gray-500">
              Invoices in the Sales Register that were not found in GSTR-1
              (G1M1 — under-reporting risk).
            </p>
            <UnmatchedCards
              rows={result.unmatched_sr || []}
              emptyTitle="No missing invoices"
            />
          </section>
        )}

        {tab === "unmatched_gstr1" && (
          <section className={sectionContainerClass}>
            <h2 className="mb-4 text-[15px] font-semibold tracking-tight text-[var(--ink)]">
              Extra in GSTR-1{" "}
              <span className="text-gray-400">
                ({summary.unmatched_gstr1_count.toLocaleString("en-IN")})
              </span>
            </h2>
            <p className="mb-4 text-[13px] text-gray-500">
              Invoices filed in GSTR-1 with no matching Sales Register entry
              (G1M2).
            </p>
            <UnmatchedCards
              rows={result.unmatched_gstr1 || []}
              emptyTitle="No extra GSTR-1 invoices"
            />
          </section>
        )}

        {tab === "tie_out" && <Gstr1TieOutPanel tieOut={result.tie_out || {}} />}

        {tab === "diagnostics" && (
          <section className={sectionContainerClass}>
            <h2 className="mb-4 text-[15px] font-semibold tracking-tight text-[var(--ink)]">
              Parse diagnostics
            </h2>
            <div className="grid gap-4 lg:grid-cols-2">
              <div className="rounded-xl bg-[#F7F7F8] px-4 py-4">
                <p className="text-[11px] font-medium uppercase tracking-widest text-gray-400">
                  Sales Register
                </p>
                <dl className="mt-3 space-y-2 text-[13px]">
                  <div className="flex justify-between gap-3">
                    <dt className="text-gray-500">Valid rows</dt>
                    <dd className="font-medium tabular-nums text-[var(--ink)]">
                      {result.parse_diagnostics?.sr?.valid_rows ?? "—"}
                    </dd>
                  </div>
                  <div className="flex justify-between gap-3">
                    <dt className="text-gray-500">Skipped</dt>
                    <dd className="font-medium tabular-nums text-[var(--ink)]">
                      {result.parse_diagnostics?.sr?.skipped_rows ?? "—"}
                    </dd>
                  </div>
                  <div className="flex justify-between gap-3">
                    <dt className="text-gray-500">Source</dt>
                    <dd className="font-medium text-[var(--ink)]">
                      {result.parse_diagnostics?.sr?.source_software || "—"}
                    </dd>
                  </div>
                </dl>
                {(result.parse_diagnostics?.sr?.warnings || []).length > 0 ? (
                  <ul className="mt-3 space-y-1 text-[12px] text-amber-800">
                    {(result.parse_diagnostics?.sr?.warnings || []).map((w) => (
                      <li key={w}>{w}</li>
                    ))}
                  </ul>
                ) : null}
              </div>
              <div className="rounded-xl bg-[#F7F7F8] px-4 py-4">
                <p className="text-[11px] font-medium uppercase tracking-widest text-gray-400">
                  GSTR-1
                </p>
                <dl className="mt-3 space-y-2 text-[13px]">
                  <div className="flex justify-between gap-3">
                    <dt className="text-gray-500">Parsed</dt>
                    <dd className="font-medium tabular-nums text-[var(--ink)]">
                      {result.parse_diagnostics?.gstr1?.total_parsed ?? "—"}
                    </dd>
                  </div>
                  <div className="flex justify-between gap-3">
                    <dt className="text-gray-500">Skipped</dt>
                    <dd className="font-medium tabular-nums text-[var(--ink)]">
                      {result.parse_diagnostics?.gstr1?.total_skipped ?? "—"}
                    </dd>
                  </div>
                  <div className="flex justify-between gap-3">
                    <dt className="text-gray-500">Filing GSTIN</dt>
                    <dd className="font-mono text-[12px] text-[var(--ink)]">
                      {result.parse_diagnostics?.gstr1?.filing_gstin || "—"}
                    </dd>
                  </div>
                </dl>
                {result.parse_diagnostics?.gstr1?.section_counts ? (
                  <div className="mt-3 flex flex-wrap gap-1.5">
                    {Object.entries(
                      result.parse_diagnostics.gstr1.section_counts
                    ).map(([sec, n]) => (
                      <span
                        key={sec}
                        className="rounded-full bg-white px-2.5 py-0.5 text-[11px] font-medium text-gray-600"
                      >
                        {sec}: {n}
                      </span>
                    ))}
                  </div>
                ) : null}
              </div>
            </div>

            {/* Full mismatch flat list */}
            <div className="mt-6">
              <p className="mb-3 text-[11px] font-medium uppercase tracking-widest text-gray-400">
                All classified mismatches ({summary.mismatch_count})
              </p>
              {(result.mismatches || []).length === 0 ? (
                <EmptyTableState title="No mismatches classified" />
              ) : (
                <ul className="space-y-2">
                  {(result.mismatches || []).map((m, i) => (
                    <li
                      key={`${m.mismatch_type}-${i}`}
                      className="rounded-xl ring-1 ring-[#F0F0F0] bg-white px-4 py-3"
                    >
                      <div className="flex flex-wrap items-center gap-2">
                        <TypePill type={m.mismatch_type} />
                        <SeverityPill severity={m.mismatch_severity} />
                        <span className="text-[13px] font-medium text-[var(--ink)]">
                          {m.decision_what || m.invoice_number || "—"}
                        </span>
                      </div>
                      {m.decision_next ? (
                        <p className="mt-1.5 text-[12px] font-medium text-[var(--ink)]">
                          {m.decision_next}
                        </p>
                      ) : null}
                    </li>
                  ))}
                </ul>
              )}
            </div>
          </section>
        )}
      </div>

      {/* Sticky footer — sales analogue of purchase finalize bar */}
      <div className="fixed bottom-3 left-[256px] right-3 z-40 max-lg:left-3">
        <div className="mx-auto flex max-w-7xl flex-wrap items-center justify-between gap-4 rounded-[1.5rem] bg-white/95 px-5 py-3.5 shadow-[var(--shadow-lift)] ring-1 ring-black/[0.04] backdrop-blur-xl">
          <div className="flex min-w-0 items-start gap-2.5 rounded-2xl bg-[#F7F7F8] px-3.5 py-2.5">
            <Check
              className="mt-0.5 h-3.5 w-3.5 shrink-0 text-gray-400"
              aria-hidden
            />
            <div className="min-w-0">
              <p className="text-[12px] font-medium text-[var(--ink)]">
                Checklist before filing
              </p>
              <p className="mt-0.5 text-[11px] leading-snug text-gray-500">
                Review Required, Missing in GSTR-1, Extra in GSTR-1, and the
                GSTR-1 vs 3B tie-out before amending returns.
              </p>
            </div>
          </div>
          <div className="flex shrink-0 flex-wrap items-center gap-2">
            {onRunAgain ? (
              <button
                type="button"
                className="inline-flex items-center gap-2 rounded-full bg-[#F5F5F6] px-5 py-2.5 text-[13px] font-semibold text-gray-700 transition-colors hover:bg-gray-200/70"
                onClick={onRunAgain}
              >
                Run again
              </button>
            ) : null}
            <button
              type="button"
              disabled={pdfBusy}
              className="inline-flex items-center gap-2 rounded-full bg-[var(--ink)] px-5 py-2.5 text-[13px] font-semibold text-white transition-opacity hover:opacity-90 disabled:opacity-50"
              onClick={() => void handlePdf()}
            >
              Export PDF report
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}
