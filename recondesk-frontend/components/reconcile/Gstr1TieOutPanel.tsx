"use client";

import { useState } from "react";

import { Drc01bReplyDraftModal } from "@/components/reconcile/Drc01bReplyDraftModal";
import type { Gstr1TieOut } from "@/lib/gstr1Reconcile";
import { formatINR } from "@/lib/format";
import {
  CompactStatAmount,
  SectionHeader,
  sectionContainerClass,
  StatCard,
  statCardsGridClass,
} from "./ResultsUi";

function parseRupeeLabel(raw: string | undefined): number | null {
  if (!raw) return null;
  // Backend formats as "₹7,698,910.71" via _rs()
  const cleaned = raw.replace(/[₹,\s]/g, "").replace(/[−–]/g, "-");
  const n = Number(cleaned);
  return Number.isFinite(n) ? n : null;
}

function VarianceDirectionBadge({
  direction,
}: {
  direction: string;
}) {
  const over = direction === "over";
  return (
    <span
      className={`inline-flex items-center rounded-full px-2.5 py-0.5 text-[11px] font-medium ${
        over
          ? "bg-amber-50 text-amber-800 ring-1 ring-amber-200"
          : "bg-red-50 text-red-700 ring-1 ring-red-200"
      }`}
    >
      {over ? "GSTR-1 higher" : "GSTR-3B higher"}
    </span>
  );
}

function CleanBadge({ clean }: { clean: boolean }) {
  if (clean) {
    return (
      <span className="inline-flex items-center gap-1.5 rounded-full bg-green-50 px-3 py-1 text-[12px] font-semibold text-green-700 ring-1 ring-green-200">
        <span className="h-1.5 w-1.5 rounded-full bg-green-500" />
        Tied out
      </span>
    );
  }
  return (
    <span className="inline-flex items-center gap-1.5 rounded-full bg-amber-50 px-3 py-1 text-[12px] font-semibold text-amber-800 ring-1 ring-amber-200">
      <span className="h-1.5 w-1.5 rounded-full bg-amber-500" />
      Variances found
    </span>
  );
}

function fieldLabel(field: string): string {
  const map: Record<string, string> = {
    taxable_value: "Taxable value",
    igst: "IGST",
    cgst: "CGST",
    sgst: "SGST",
    cess: "CESS",
    total_tax: "Total tax",
  };
  return map[field] || field;
}

function AggregateCompare({
  label,
  g1Paise,
  g3Paise,
}: {
  label: string;
  g1Paise: number;
  g3Paise: number;
}) {
  const g1 = g1Paise / 100;
  const g3 = g3Paise / 100;
  const diff = g1 - g3;
  return (
    <tr className="border-b border-[#F0F0F0] last:border-b-0">
      <td className="px-4 py-3 text-[13px] font-medium text-[var(--ink)]">
        {label}
      </td>
      <td className="px-4 py-3 text-right text-[13px] tabular-nums text-gray-700">
        {formatINR(g1)}
      </td>
      <td className="px-4 py-3 text-right text-[13px] tabular-nums text-gray-700">
        {formatINR(g3)}
      </td>
      <td
        className={`px-4 py-3 text-right text-[13px] font-semibold tabular-nums ${
          Math.abs(diff) < 0.01
            ? "text-gray-500"
            : diff > 0
              ? "text-amber-800"
              : "text-red-700"
        }`}
      >
        {Math.abs(diff) < 0.01
          ? "—"
          : `${diff > 0 ? "+" : "−"}${formatINR(Math.abs(diff))}`}
      </td>
    </tr>
  );
}

export function Gstr1TieOutPanel({
  tieOut,
  clientName = "",
  clientGstin = "",
}: {
  tieOut: Gstr1TieOut;
  /** Taxpayer legal / trade name for DRC-01B draft header. */
  clientName?: string;
  /** Filing GSTIN for DRC-01B draft header. */
  clientGstin?: string;
}) {
  const [drc01bOpen, setDrc01bOpen] = useState(false);
  const isClean = Boolean(tieOut.is_clean);
  const variances = tieOut.variances || [];
  const decisions = tieOut.mismatch_decisions || [];
  const g1 = tieOut.gstr1 || {};
  const g3 = tieOut.gstr3b || {};

  const unexplainedDiff =
    typeof tieOut.unexplained_difference === "number"
      ? tieOut.unexplained_difference
      : typeof tieOut.unexplained_difference_paise === "number"
        ? tieOut.unexplained_difference_paise / 100
        : parseRupeeLabel(
            variances.find((v) => v.field === "taxable_value")?.diff
          ) ?? Math.abs((g1.taxable_value_paise || 0) - (g3.taxable_value_paise || 0)) / 100;

  const reclassificationDiff =
    typeof tieOut.reclassification_difference === "number"
      ? tieOut.reclassification_difference
      : typeof tieOut.reclassification_difference_paise === "number"
        ? tieOut.reclassification_difference_paise / 100
        : 0;

  const totalTaxDiff =
    parseRupeeLabel(variances.find((v) => v.field === "total_tax")?.diff) ??
    Math.abs((g1.total_tax_paise || 0) - (g3.total_tax_paise || 0)) / 100;

  const stat = tieOut.statutory_reconciliation || {};
  const taxableOutward = tieOut.taxable_outward || stat.taxable_outward;
  const zeroRated = tieOut.zero_rated || stat.zero_rated;
  const nilExempt = tieOut.nil_exempt || stat.nil_exempt;
  const nonGst = tieOut.non_gst || stat.non_gst;

  return (
    <section className={sectionContainerClass} aria-label="GSTR-1 vs GSTR-3B tie-out">
      <SectionHeader
        title="GSTR-1 vs GSTR-3B"
        dotColor={isClean ? "#22C55E" : "#F59E0B"}
        actions={
          <div className="flex flex-wrap items-center gap-2">
            {!isClean ? (
              <button
                type="button"
                onClick={() => setDrc01bOpen(true)}
                className="rounded-full border border-[#E5E7EB] bg-white px-3 py-1.5 text-[12px] font-semibold text-[var(--ink)] transition-colors hover:bg-[#F7F7F8]"
              >
                Draft DRC-01B reply
              </button>
            ) : null}
            <CleanBadge clean={isClean} />
          </div>
        }
      />
      <p className="mt-1 text-[13px] text-gray-500">
        Table 3.1 outward supplies & tax tie-out — period{" "}
        <span className="font-medium text-[var(--ink)]">
          {tieOut.ret_period || "—"}
        </span>
        {typeof tieOut.gstr1_record_count === "number" ? (
          <>
            {" "}
            · {tieOut.gstr1_record_count.toLocaleString("en-IN")} GSTR-1
            invoice{tieOut.gstr1_record_count === 1 ? "" : "s"} aggregated
          </>
        ) : null}
      </p>

      {reclassificationDiff > 0.01 ? (
        <div className="mt-3 flex items-start gap-2.5 rounded-xl border border-blue-100 bg-blue-50/60 px-4 py-3 text-[12px] text-blue-900">
          <div className="mt-0.5 h-1.5 w-1.5 shrink-0 rounded-full bg-blue-600" />
          <div className="min-w-0">
            <span className="font-semibold text-blue-950">Statutory Allocation Accounted For:</span>{" "}
            {formatINR(reclassificationDiff)} belongs to nil-rated/exempt supplies reported in Table 8 / 3.1(c) rather than 3.1(a).
            {unexplainedDiff < 0.01 ? " Genuine unexplained financial variance is ₹0 (Clean)." : ` Unexplained variance: ${formatINR(unexplainedDiff)}.`}
          </div>
        </div>
      ) : null}

      <div className={statCardsGridClass}>
        <StatCard
          label="Tie-out status"
          value={isClean ? "Clean" : "Needs review"}
          accent={isClean ? "matched" : "review_required"}
          emphasis={isClean ? "secondary" : "attention"}
          subtext={
            isClean
              ? "Within ₹1 rounding tolerance"
              : `${variances.length} variance${variances.length === 1 ? "" : "s"}`
          }
        />
        <StatCard
          label="Unexplained variance"
          accent={unexplainedDiff > 0.01 ? "risk" : "neutral"}
          emphasis={unexplainedDiff > 0.01 ? "danger" : "secondary"}
          value={
            <CompactStatAmount
              amount={unexplainedDiff}
              emphasize={unexplainedDiff > 0.01}
              className={unexplainedDiff > 0.01 ? "text-amber-800" : undefined}
            />
          }
          subtext="Net financial difference"
        />
        <StatCard
          label="Total tax variance"
          accent={totalTaxDiff > 0.01 ? "missed" : "neutral"}
          emphasis={totalTaxDiff > 0.01 ? "danger" : "secondary"}
          value={
            <CompactStatAmount
              amount={totalTaxDiff}
              emphasize={totalTaxDiff > 0.01}
              className={totalTaxDiff > 0.01 ? "text-red-700" : undefined}
            />
          }
          subtext="IGST + CGST + SGST + CESS"
        />
      </div>

      <div className="mt-5 overflow-x-auto rounded-xl border border-[#F0F0F0]">
        <table className="w-full table-fixed border-collapse text-left text-[13px]">
          <colgroup>
            <col style={{ width: "28%" }} />
            <col style={{ width: "24%" }} />
            <col style={{ width: "24%" }} />
            <col style={{ width: "24%" }} />
          </colgroup>
          <thead>
            <tr className="border-b border-[#F0F0F0] bg-[#FAFAFB] text-[11px] font-medium uppercase tracking-widest text-gray-400">
              <th className="px-4 py-3">Statutory Supply Section</th>
              <th className="px-4 py-3 text-right">GSTR-1</th>
              <th className="px-4 py-3 text-right">GSTR-3B</th>
              <th className="px-4 py-3 text-right">Difference</th>
            </tr>
          </thead>
          <tbody>
            <AggregateCompare
              label="3.1(a) Taxable Outward"
              g1Paise={taxableOutward?.gstr1_value_paise ?? g1.taxable_value_paise ?? 0}
              g3Paise={taxableOutward?.gstr3b_value_paise ?? g3.taxable_value_paise ?? 0}
            />
            {zeroRated && (zeroRated.gstr1_value_paise > 0 || zeroRated.gstr3b_value_paise > 0) ? (
              <AggregateCompare
                label="3.1(b) Zero-Rated (Exports/SEZ)"
                g1Paise={zeroRated.gstr1_value_paise}
                g3Paise={zeroRated.gstr3b_value_paise}
              />
            ) : null}
            {nilExempt && (nilExempt.gstr1_value_paise > 0 || nilExempt.gstr3b_value_paise > 0) ? (
              <AggregateCompare
                label="3.1(c) Nil / Exempt / Table 8"
                g1Paise={nilExempt.gstr1_value_paise}
                g3Paise={nilExempt.gstr3b_value_paise}
              />
            ) : null}
            {nonGst && (nonGst.gstr1_value_paise > 0 || nonGst.gstr3b_value_paise > 0) ? (
              <AggregateCompare
                label="3.1(e) Non-GST Outward"
                g1Paise={nonGst.gstr1_value_paise}
                g3Paise={nonGst.gstr3b_value_paise}
              />
            ) : null}
            <AggregateCompare
              label="IGST"
              g1Paise={g1.igst_paise || 0}
              g3Paise={g3.igst_paise || 0}
            />
            <AggregateCompare
              label="CGST"
              g1Paise={g1.cgst_paise || 0}
              g3Paise={g3.cgst_paise || 0}
            />
            <AggregateCompare
              label="SGST"
              g1Paise={g1.sgst_paise || 0}
              g3Paise={g3.sgst_paise || 0}
            />
            <AggregateCompare
              label="Total tax"
              g1Paise={g1.total_tax_paise || 0}
              g3Paise={g3.total_tax_paise || 0}
            />
          </tbody>
        </table>
      </div>

      {variances.length > 0 ? (
        <div className="mt-5 space-y-2">
          <p className="text-[11px] font-medium uppercase tracking-widest text-gray-400">
            Flagged variances
          </p>
          <ul className="space-y-2">
            {variances.map((v) => (
              <li
                key={`${v.field}-${v.diff}`}
                className="flex flex-wrap items-center justify-between gap-2 rounded-xl bg-[#F7F7F8] px-4 py-3"
              >
                <div className="min-w-0">
                  <p className="text-[13px] font-medium text-[var(--ink)]">
                    {fieldLabel(v.field)}
                  </p>
                  <p className="mt-0.5 text-[12px] text-gray-500">
                    GSTR-1 {v.gstr1} · 3B {v.gstr3b} · diff {v.diff}
                  </p>
                </div>
                <VarianceDirectionBadge direction={v.direction} />
              </li>
            ))}
          </ul>
        </div>
      ) : (
        <p className="mt-5 text-[12px] italic text-gray-400">
          No variance exceeds the ₹1 rounding tolerance. Outward supply
          figures tie out between GSTR-1 and GSTR-3B.
        </p>
      )}

      {decisions.length > 0 ? (
        <div className="mt-5 space-y-2">
          <p className="text-[11px] font-medium uppercase tracking-widest text-gray-400">
            Tie-out decisions
          </p>
          {decisions.map((d, i) => (
            <div
              key={`${d.mismatch_type || "v"}-${i}`}
              className="rounded-xl ring-1 ring-[#F0F0F0] bg-white px-4 py-3"
            >
              <p className="text-[13px] font-medium text-[var(--ink)]">
                {d.decision_what || d.mismatch_type}
              </p>
              {d.decision_why ? (
                <p className="mt-1 text-[12px] italic text-gray-500">
                  {d.decision_why}
                </p>
              ) : null}
              {d.decision_next ? (
                <p className="mt-1 text-[12px] font-medium text-[var(--ink)]">
                  {d.decision_next}
                </p>
              ) : null}
            </div>
          ))}
        </div>
      ) : null}

      <Drc01bReplyDraftModal
        open={drc01bOpen}
        onClose={() => setDrc01bOpen(false)}
        tieOut={tieOut}
        clientName={clientName}
        clientGstin={clientGstin}
      />
    </section>
  );
}
