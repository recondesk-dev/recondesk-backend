/**
 * Client-side Excel (CSV) + PDF export for GSTR-1 sales reconciliation results.
 * Purchase-side AdvancedExportPanel stays untouched (run-id / server export).
 */

import { jsPDF } from "jspdf";

import { downloadBlobAsFile, pdfBytesToBlob } from "@/lib/download";
import {
  countMismatchesByType,
  filterReviewRequired,
  groupGstr1aEligibleByPeriod,
  gstr1RunPeriodLabel,
  mismatchTypeShort,
  paiseToRupees,
  recordAmountRupees,
  recordGstin,
  recordInvoiceNumber,
  type Gstr1DecisionFields,
  type Gstr1MatchedRow,
  type Gstr1ReconcileResult,
  type Gstr1UnmatchedRow,
} from "@/lib/gstr1Reconcile";

function csvEscape(value: unknown): string {
  const s = value == null ? "" : String(value);
  if (/[",\n\r]/.test(s)) return `"${s.replace(/"/g, '""')}"`;
  return s;
}

function rowsToCsv(headers: string[], rows: unknown[][]): string {
  const lines = [
    headers.map(csvEscape).join(","),
    ...rows.map((r) => r.map(csvEscape).join(",")),
  ];
  return lines.join("\n");
}

function matchedCsvRows(rows: Gstr1MatchedRow[]): unknown[][] {
  return rows.map((row) => {
    const sr = row.sr_record || {};
    return [
      recordInvoiceNumber(sr),
      recordGstin(sr) || "B2C",
      sr.invoice_date || "",
      recordAmountRupees(sr).toFixed(2),
      row.match_level ?? "",
      row.confidence ?? "",
      row.decision_confidence || "",
      (row.discrepancies || []).join("; "),
      row.decision_what || "",
      row.decision_why || "",
      row.decision_next || "",
    ];
  });
}

function unmatchedCsvRows(rows: Gstr1UnmatchedRow[]): unknown[][] {
  return rows.map((row) => {
    const rec = row.record || {};
    return [
      mismatchTypeShort(row.mismatch_type),
      row.mismatch_severity || "",
      recordInvoiceNumber(rec),
      recordGstin(rec) || row.recipient_gstin || "B2C",
      rec.invoice_date || "",
      recordAmountRupees(rec).toFixed(2),
      row.decision_what || "",
      row.decision_why || "",
      row.decision_next || "",
    ];
  });
}

export function downloadGstr1ExcelReport(result: Gstr1ReconcileResult): void {
  const stamp = new Date().toISOString().slice(0, 10);
  const sections: string[] = [];

  sections.push("=== Summary ===");
  sections.push(
    rowsToCsv(
      ["metric", "value"],
      [
        ["sr_total_records", result.summary.sr_total_records],
        ["gstr1_total_records", result.summary.gstr1_total_records],
        ["matched_count", result.summary.matched_count],
        ["unmatched_sr_count", result.summary.unmatched_sr_count],
        ["unmatched_gstr1_count", result.summary.unmatched_gstr1_count],
        ["mismatch_count", result.summary.mismatch_count],
        ["tie_out_clean", result.summary.tie_out_clean],
        ["tie_out_variance_count", result.summary.tie_out_variance_count],
      ]
    )
  );

  sections.push("\n=== Matched ===");
  sections.push(
    rowsToCsv(
      [
        "invoice",
        "gstin",
        "date",
        "taxable",
        "match_level",
        "confidence",
        "decision_confidence",
        "discrepancies",
        "what",
        "why",
        "next",
      ],
      matchedCsvRows(result.matched || [])
    )
  );

  sections.push("\n=== Review Required ===");
  sections.push(
    rowsToCsv(
      [
        "invoice",
        "gstin",
        "date",
        "taxable",
        "match_level",
        "confidence",
        "decision_confidence",
        "discrepancies",
        "what",
        "why",
        "next",
      ],
      matchedCsvRows(filterReviewRequired(result.matched || []))
    )
  );

  sections.push("\n=== Missing in GSTR-1 (G1M1) ===");
  sections.push(
    rowsToCsv(
      [
        "type",
        "severity",
        "invoice",
        "gstin",
        "date",
        "taxable",
        "what",
        "why",
        "next",
      ],
      unmatchedCsvRows(result.unmatched_sr || [])
    )
  );

  sections.push("\n=== Extra in GSTR-1 (G1M2) ===");
  sections.push(
    rowsToCsv(
      [
        "type",
        "severity",
        "invoice",
        "gstin",
        "date",
        "taxable",
        "what",
        "why",
        "next",
      ],
      unmatchedCsvRows(result.unmatched_gstr1 || [])
    )
  );

  sections.push("\n=== All mismatches ===");
  sections.push(
    rowsToCsv(
      ["type", "severity", "invoice", "gstin", "what", "why", "next"],
      (result.mismatches || []).map((m) => [
        mismatchTypeShort(m.mismatch_type),
        m.mismatch_severity || "",
        m.invoice_number || "",
        m.recipient_gstin || "",
        m.decision_what || "",
        m.decision_why || "",
        m.decision_next || "",
      ])
    )
  );

  const tie = result.tie_out || {};
  sections.push("\n=== GSTR-1 vs 3B variances ===");
  sections.push(
    rowsToCsv(
      ["field", "gstr1", "gstr3b", "diff", "direction"],
      (tie.variances || []).map((v) => [
        v.field,
        v.gstr1,
        v.gstr3b,
        v.diff,
        v.direction,
      ])
    )
  );

  const blob = new Blob([sections.join("\n")], {
    type: "text/csv;charset=utf-8",
  });
  downloadBlobAsFile(blob, `gstr1-reconcile-${stamp}.csv`);
}

function mismatchPaise(
  m: Gstr1DecisionFields,
  ...keys: string[]
): number | null {
  for (const key of keys) {
    const v = m[key];
    if (v == null || v === "") continue;
    const n = Number(v);
    if (!Number.isNaN(n)) return n;
  }
  return null;
}

/**
 * Excel (CSV) export of GSTR-1A-eligible mismatches for the batch summary screen.
 * Same download path as {@link downloadGstr1ExcelReport}.
 */
export function downloadGstr1aReadyExcel(result: Gstr1ReconcileResult): void {
  const stamp = new Date().toISOString().slice(0, 10);
  const fallbackPeriod = gstr1RunPeriodLabel(result) || "—";
  const groups = groupGstr1aEligibleByPeriod(
    result.mismatches || [],
    fallbackPeriod
  );

  const headers = [
    "period",
    "invoice_number",
    "gstin",
    "taxable_value",
    "tax_amount",
    "mismatch_type",
    "note",
  ];

  const rows: unknown[][] = [];
  for (const group of groups) {
    for (const m of group.mismatches) {
      const taxablePaise = mismatchPaise(
        m,
        "taxable_amount_paise",
        "sr_taxable_paise",
        "gstr1_taxable_paise"
      );
      const taxPaise = mismatchPaise(
        m,
        "total_tax_paise",
        "sr_tax_paise",
        "gstr1_tax_paise"
      );
      const gstin =
        (m.recipient_gstin != null && String(m.recipient_gstin).trim()) ||
        (m.gstin != null && String(m.gstin).trim()) ||
        (m.sr_gstin != null && String(m.sr_gstin).trim()) ||
        "";

      rows.push([
        group.period,
        m.invoice_number || "",
        gstin,
        taxablePaise != null ? paiseToRupees(taxablePaise).toFixed(2) : "",
        taxPaise != null ? paiseToRupees(taxPaise).toFixed(2) : "",
        mismatchTypeShort(m.mismatch_type),
        m.note || "",
      ]);
    }
  }

  const csv = rowsToCsv(headers, rows);
  const blob = new Blob([csv], { type: "text/csv;charset=utf-8" });
  downloadBlobAsFile(blob, `gstr1a-ready-${stamp}.csv`);
}

export async function downloadGstr1PdfReport(
  result: Gstr1ReconcileResult
): Promise<void> {
  const doc = new jsPDF({ unit: "pt", format: "a4" });
  const margin = 48;
  let y = margin;
  const pageWidth = doc.internal.pageSize.getWidth();
  const maxWidth = pageWidth - margin * 2;

  const line = (text: string, opts?: { bold?: boolean; size?: number }) => {
    doc.setFont("helvetica", opts?.bold ? "bold" : "normal");
    doc.setFontSize(opts?.size ?? 10);
    const lines = doc.splitTextToSize(text, maxWidth) as string[];
    for (const l of lines) {
      if (y > doc.internal.pageSize.getHeight() - margin) {
        doc.addPage();
        y = margin;
      }
      doc.text(l, margin, y);
      y += (opts?.size ?? 10) + 4;
    }
  };

  const s = result.summary;
  const counts = countMismatchesByType(result.mismatches || []);
  const review = filterReviewRequired(result.matched || []);

  line("ReconDesk — GSTR-1 Sales Reconciliation", { bold: true, size: 14 });
  y += 6;
  line(
    `Generated ${new Date().toLocaleString("en-IN")} · Period ${
      result.meta?.filing_period ||
      result.tie_out?.ret_period ||
      result.parse_diagnostics?.gstr1?.filing_period ||
      "—"
    }`
  );
  y += 10;

  line("Summary", { bold: true, size: 12 });
  line(
    `Sales Register: ${s.sr_total_records} · GSTR-1: ${s.gstr1_total_records} · Matched: ${s.matched_count} · Review Required: ${review.length}`
  );
  const fieldMismatches =
    (counts.G1M3 || 0) +
    (counts.G1M4 || 0) +
    (counts.G1M5 || 0) +
    (counts.G1M6 || 0) +
    (counts.G1M7 || 0) +
    (counts.G1M8 || 0) +
    (counts.G1M9 || 0);
  line(
    `Missing in GSTR-1: ${s.unmatched_sr_count} · Extra in GSTR-1: ${s.unmatched_gstr1_count} · Field mismatches (G1M3–G1M9): ${fieldMismatches}`
  );
  line(
    `Tie-out: ${s.tie_out_clean ? "Clean" : "Variances"} (${s.tie_out_variance_count})`
  );
  y += 8;

  line("Mismatch types", { bold: true, size: 12 });
  const typeLine = Object.entries(counts)
    .map(([k, v]) => `${k}: ${v}`)
    .join(" · ");
  line(typeLine || "None");
  y += 8;

  line("GSTR-1 vs GSTR-3B", { bold: true, size: 12 });
  const g1 = result.tie_out?.gstr1 || {};
  const g3 = result.tie_out?.gstr3b || {};
  line(
    `Taxable GSTR-1 ₹${paiseToRupees(g1.taxable_value_paise).toLocaleString("en-IN")} vs 3B ₹${paiseToRupees(g3.taxable_value_paise).toLocaleString("en-IN")}`
  );
  for (const v of result.tie_out?.variances || []) {
    line(`${v.field}: ${v.diff} (${v.direction})`);
  }
  y += 8;

  line("Review Required (sample)", { bold: true, size: 12 });
  for (const row of review.slice(0, 25)) {
    const inv = recordInvoiceNumber(row.sr_record);
    line(
      `${inv} · conf ${row.confidence ?? "—"} · ${row.decision_what || row.review_reason || "Needs review"}`
    );
  }
  if (review.length > 25) {
    line(`…and ${review.length - 25} more`);
  }

  const bytes = doc.output("arraybuffer");
  downloadBlobAsFile(
    pdfBytesToBlob(bytes),
    `gstr1-reconcile-${new Date().toISOString().slice(0, 10)}.pdf`
  );
}
