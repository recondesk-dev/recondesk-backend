/**
 * Rule 37 Compliance PDF — premium CA-firm deliverable (jsPDF + autoTable).
 */

import { formatINR } from "@/lib/format";
import {
  formatRule37ActionLabel,
  formatRule37ActionTimeIst,
  type Rule37ActionHistoryRow,
  type Rule37SummaryStats,
} from "@/lib/rule37Summary";

// Brand palette
const PURPLE: [number, number, number] = [124, 58, 237];
const CHARCOAL: [number, number, number] = [26, 26, 46];
const GREY_TEXT: [number, number, number] = [107, 114, 128];
const GREY_LIGHT: [number, number, number] = [248, 248, 248];
const GREEN: [number, number, number] = [22, 163, 74];
const RED: [number, number, number] = [220, 38, 38];
const ORANGE: [number, number, number] = [217, 119, 6];
const URGENT_FILL: [number, number, number] = [255, 235, 235];
const WHITE: [number, number, number] = [255, 255, 255];
const BORDER_GREY: [number, number, number] = [229, 231, 235];

const MARGIN = 15;
const CONTENT_TOP = 22;
const FOOTER_Y = 285;

export type Rule37ExportInvoiceRow = {
  invoice_number: string;
  supplier_gstin: string;
  invoice_date: string;
  amount: number;
  deadline?: string | null;
  days_remaining?: number | null;
};

export type Rule37ExportActedInvoiceRow = Rule37ExportInvoiceRow & {
  acted_on: string;
  acted_by_name: string;
};

export type Rule37ExportFollowupRow = {
  supplier_name: string;
  supplier_gstin: string;
  invoice_numbers: string;
  action: string;
  date: string;
};

export type Rule37CompliancePdfData = {
  client_name: string;
  client_gstin: string;
  tax_period_display: string;
  prepared_by_name: string;
  summary: Rule37SummaryStats;
  action_history: Rule37ActionHistoryRow[];
  pending_invoices: Rule37ExportInvoiceRow[];
  secured_invoices: Rule37ExportActedInvoiceRow[];
  reversed_invoices: Rule37ExportActedInvoiceRow[];
  followup_log: Rule37ExportFollowupRow[];
};

type JsPdfDoc = import("jspdf").jsPDF;
type AutoTableFn = typeof import("jspdf-autotable").default;

function formatIstDate(iso: string): string {
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return "—";
  return d.toLocaleDateString("en-IN", { timeZone: "Asia/Kolkata" });
}

function formatGeneratedDate(d = new Date()): string {
  return d.toLocaleDateString("en-IN", {
    day: "2-digit",
    month: "short",
    year: "numeric",
    timeZone: "Asia/Kolkata",
  });
}

function formatDeadlineDisplay(deadline?: string | null): string {
  if (!deadline?.trim()) return "—";
  return formatIstDate(deadline.includes("T") ? deadline : `${deadline}T00:00:00`);
}

export function rule37CompliancePdfFilename(
  clientGstin: string,
  taxPeriod: string
): string {
  const gstin =
    (clientGstin || "client").replace(/[^A-Za-z0-9]/g, "").toUpperCase() ||
    "CLIENT";
  const period = (taxPeriod || "period")
    .replace(/[^A-Za-z0-9]/g, "-")
    .replace(/-+/g, "-")
    .replace(/^-|-$/g, "");
  return `Rule37-Compliance-${gstin}-${period || "period"}.pdf`;
}

function buildExecutiveSummary(summary: Rule37SummaryStats): string {
  const total = formatINR(summary.total_itc_at_risk);
  const saved = formatINR(summary.itc_saved);
  const reversed = formatINR(summary.itc_reversed);
  const pending = formatINR(summary.pending_action);

  if (summary.total_itc_at_risk <= 0) {
    return "No Rule 37 ITC exposure was identified for this tax period. All tracked supplier payments are within compliance thresholds.";
  }
  if (summary.pending_action <= 0 && summary.itc_reversed <= 0) {
    return `This reconciliation tracked ${total} in Rule 37 ITC exposure. ${saved} has been secured through confirmed supplier payments, and no amounts remain pending immediate action.`;
  }
  if (summary.pending_action > 0 && summary.itc_saved <= 0) {
    return `This reconciliation tracked ${total} in Rule 37 ITC exposure. ${pending} requires immediate attention to avoid mandatory ITC reversal. ${reversed} has already been reversed in the records.`;
  }
  return `This reconciliation tracked ${total} in Rule 37 ITC exposure. ${saved} has been secured through confirmed supplier payments, ${reversed} has been reversed, and ${pending} remains pending immediate action.`;
}

function drawCoverPage(
  doc: JsPdfDoc,
  data: Rule37CompliancePdfData,
  pageW: number,
  pageH: number
): void {
  doc.setFont("helvetica", "bold");
  doc.setFontSize(18);
  doc.setTextColor(...PURPLE);
  doc.text("ReconDesk", MARGIN, 20);

  doc.setDrawColor(...PURPLE);
  doc.setLineWidth(0.35);
  doc.line(MARGIN, 24, pageW - MARGIN, 24);

  const centerY = pageH * 0.42;
  doc.setFont("helvetica", "normal");
  doc.setFontSize(9);
  doc.setTextColor(...GREY_TEXT);
  doc.text("RECONCILIATION REPORT — RULE 37 COMPLIANCE", pageW / 2, centerY, {
    align: "center",
  });

  doc.setFont("helvetica", "bold");
  doc.setFontSize(22);
  doc.setTextColor(...CHARCOAL);
  doc.text(data.client_name || "—", pageW / 2, centerY + 12, {
    align: "center",
  });

  doc.setFont("courier", "normal");
  doc.setFontSize(10);
  doc.setTextColor(...GREY_TEXT);
  doc.text(data.client_gstin || "—", pageW / 2, centerY + 22, {
    align: "center",
  });

  doc.setFont("helvetica", "normal");
  doc.setFontSize(10);
  doc.text(
    `Period: ${data.tax_period_display || "—"}`,
    pageW / 2,
    centerY + 30,
    { align: "center" }
  );

  const bottomY = pageH - 48;
  doc.setDrawColor(...BORDER_GREY);
  doc.setLineWidth(0.25);
  doc.line(MARGIN, bottomY, pageW - MARGIN, bottomY);

  doc.setFontSize(9);
  doc.setTextColor(...CHARCOAL);
  doc.setFont("helvetica", "normal");
  const prepared = data.prepared_by_name?.trim() || "—";
  doc.text(`Prepared by: ${prepared}`, MARGIN, bottomY + 8);
  doc.text(`Generated: ${formatGeneratedDate()}`, MARGIN, bottomY + 14);

  doc.text("ReconDesk | recondesk.in", pageW - MARGIN, bottomY + 8, {
    align: "right",
  });

  doc.setFontSize(7);
  doc.setFont("helvetica", "italic");
  doc.setTextColor(...GREY_TEXT);
  doc.text(
    "This report is system-generated for informational purposes only and does not constitute legal advice.",
    pageW / 2,
    pageH - 10,
    { align: "center", maxWidth: pageW - MARGIN * 2 }
  );
}

function drawSectionHeader(
  doc: JsPdfDoc,
  title: string,
  y: number,
  pageW: number
): number {
  doc.setFont("helvetica", "bold");
  doc.setFontSize(14);
  doc.setTextColor(...CHARCOAL);
  doc.text(title, MARGIN, y);
  doc.setDrawColor(...PURPLE);
  doc.setLineWidth(0.35);
  doc.line(MARGIN, y + 2, pageW - MARGIN, y + 2);
  return y + 9;
}

function drawSubtitle(doc: JsPdfDoc, text: string, y: number): number {
  doc.setFont("helvetica", "normal");
  doc.setFontSize(9);
  doc.setTextColor(...GREY_TEXT);
  doc.text(text, MARGIN, y);
  return y + 6;
}

function drawSummaryBoxes(
  doc: JsPdfDoc,
  summary: Rule37SummaryStats,
  startY: number,
  pageW: number
): number {
  const gap = 4;
  const boxW = (pageW - MARGIN * 2 - gap) / 2;
  const boxH = 24;
  const items: {
    label: string;
    amount: number;
    color: [number, number, number];
  }[] = [
    { label: "Total ITC Tracked", amount: summary.total_itc_at_risk, color: CHARCOAL },
    { label: "ITC Secured", amount: summary.itc_saved, color: GREEN },
    { label: "ITC Reversed", amount: summary.itc_reversed, color: RED },
    { label: "Pending Action", amount: summary.pending_action, color: ORANGE },
  ];

  let y = startY;
  for (let row = 0; row < 2; row++) {
    for (let col = 0; col < 2; col++) {
      const idx = row * 2 + col;
      const item = items[idx];
      const x = MARGIN + col * (boxW + gap);
      doc.setDrawColor(...BORDER_GREY);
      doc.setLineWidth(0.25);
      doc.setFillColor(...WHITE);
      doc.roundedRect(x, y, boxW, boxH, 2, 2, "FD");

      doc.setFont("helvetica", "normal");
      doc.setFontSize(8);
      doc.setTextColor(...GREY_TEXT);
      doc.text(item.label, x + 4, y + 8);

      doc.setFont("helvetica", "bold");
      doc.setFontSize(14);
      doc.setTextColor(...item.color);
      doc.text(formatINR(item.amount), x + 4, y + 18);
    }
    y += boxH + gap;
  }
  return y + 4;
}

function tableDefaults() {
  return {
    theme: "plain" as const,
    styles: {
      font: "helvetica",
      fontSize: 9,
      textColor: CHARCOAL,
      cellPadding: 2.5,
      lineColor: BORDER_GREY,
      lineWidth: 0.1,
    },
    headStyles: {
      fillColor: PURPLE,
      textColor: WHITE,
      fontStyle: "bold" as const,
      fontSize: 9,
    },
    alternateRowStyles: {
      fillColor: GREY_LIGHT,
    },
    margin: { left: MARGIN, right: MARGIN, top: CONTENT_TOP, bottom: 14 },
  };
}

function drawHeader(doc: JsPdfDoc, pageW: number): void {
  doc.setDrawColor(...PURPLE);
  doc.setLineWidth(0.5);
  doc.line(0, 6, pageW, 6);

  doc.setFont("helvetica", "normal");
  doc.setFontSize(8);
  doc.setTextColor(...GREY_TEXT);
  doc.text("ReconDesk", MARGIN, 12);
  doc.text("Rule 37 Compliance Report", pageW - MARGIN, 12, { align: "right" });
}

function drawFooter(
  doc: JsPdfDoc,
  pageW: number,
  pageNum: number,
  totalPages: number
): void {
  doc.setDrawColor(...BORDER_GREY);
  doc.setLineWidth(0.2);
  doc.line(MARGIN, FOOTER_Y - 4, pageW - MARGIN, FOOTER_Y - 4);

  doc.setFont("helvetica", "normal");
  doc.setFontSize(7);
  doc.setTextColor(...GREY_TEXT);
  doc.text("Generated by ReconDesk | recondesk.in", MARGIN, FOOTER_Y);
  doc.text(`Page ${pageNum} of ${totalPages}`, pageW - MARGIN, FOOTER_Y, {
    align: "right",
  });
}

function drawEmptyState(doc: JsPdfDoc, message: string, y: number, pageW: number): void {
  doc.setFont("helvetica", "italic");
  doc.setFontSize(9);
  doc.setTextColor(...GREY_TEXT);
  doc.text(message, pageW / 2, y + 10, { align: "center" });
}

function renderActionHistoryTable(
  doc: JsPdfDoc,
  autoTable: AutoTableFn,
  history: Rule37ActionHistoryRow[],
  startY: number
): void {
  if (history.length === 0) {
    drawEmptyState(
      doc,
      "No actions taken yet for this period.",
      startY,
      doc.internal.pageSize.getWidth()
    );
    return;
  }

  autoTable(doc, {
    ...tableDefaults(),
    startY,
    head: [["#", "Invoice", "Supplier GSTIN", "Amount (₹)", "Action", "Date", "By"]],
    body: history.map((row, i) => [
      String(i + 1),
      row.invoice_number || "—",
      row.supplier_gstin || "—",
      formatINR(row.amount),
      formatRule37ActionLabel(row.action),
      formatRule37ActionTimeIst(row.created_at),
      row.generated_by_name?.trim() || "—",
    ]),
  });
}

function renderPendingTable(
  doc: JsPdfDoc,
  autoTable: AutoTableFn,
  rows: Rule37ExportInvoiceRow[],
  startY: number
): void {
  const pageW = doc.internal.pageSize.getWidth();
  if (rows.length === 0) {
    drawEmptyState(doc, "No invoices require immediate action.", startY, pageW);
    return;
  }

  autoTable(doc, {
    ...tableDefaults(),
    startY,
    head: [
      [
        "#",
        "Invoice Number",
        "Supplier GSTIN",
        "Invoice Date",
        "Amount (₹)",
        "Deadline",
        "Days Left",
      ],
    ],
    body: rows.map((row, i) => [
      String(i + 1),
      row.invoice_number || "—",
      row.supplier_gstin || "—",
      formatIstDate(row.invoice_date),
      formatINR(row.amount),
      formatDeadlineDisplay(row.deadline),
      row.days_remaining != null ? String(row.days_remaining) : "—",
    ]),
    didParseCell: (data) => {
      if (data.section !== "body") return;
      const row = rows[data.row.index];
      if (row?.days_remaining != null && row.days_remaining < 30) {
        data.cell.styles.fillColor = URGENT_FILL;
      }
    },
  });
}

function renderSecuredTable(
  doc: JsPdfDoc,
  autoTable: AutoTableFn,
  rows: Rule37ExportActedInvoiceRow[],
  startY: number
): void {
  const pageW = doc.internal.pageSize.getWidth();
  if (rows.length === 0) {
    drawEmptyState(doc, "No ITC secured entries for this period.", startY, pageW);
    return;
  }

  autoTable(doc, {
    ...tableDefaults(),
    startY,
    head: [
      [
        "#",
        "Invoice Number",
        "Supplier GSTIN",
        "Invoice Date",
        "Amount (₹)",
        "Confirmed On",
        "By",
      ],
    ],
    body: rows.map((row, i) => [
      String(i + 1),
      row.invoice_number || "—",
      row.supplier_gstin || "—",
      formatIstDate(row.invoice_date),
      formatINR(row.amount),
      formatRule37ActionTimeIst(row.acted_on),
      row.acted_by_name?.trim() || "—",
    ]),
  });
}

function renderReversedTable(
  doc: JsPdfDoc,
  autoTable: AutoTableFn,
  rows: Rule37ExportActedInvoiceRow[],
  startY: number
): void {
  const pageW = doc.internal.pageSize.getWidth();
  if (rows.length === 0) {
    drawEmptyState(doc, "No ITC reversed entries for this period.", startY, pageW);
    return;
  }

  autoTable(doc, {
    ...tableDefaults(),
    startY,
    head: [
      [
        "#",
        "Invoice Number",
        "Supplier GSTIN",
        "Invoice Date",
        "Amount (₹)",
        "Reversed On",
        "By",
      ],
    ],
    body: rows.map((row, i) => [
      String(i + 1),
      row.invoice_number || "—",
      row.supplier_gstin || "—",
      formatIstDate(row.invoice_date),
      formatINR(row.amount),
      formatRule37ActionTimeIst(row.acted_on),
      row.acted_by_name?.trim() || "—",
    ]),
  });
}

function renderFollowupTable(
  doc: JsPdfDoc,
  autoTable: AutoTableFn,
  rows: Rule37ExportFollowupRow[],
  startY: number
): void {
  const pageW = doc.internal.pageSize.getWidth();
  if (rows.length === 0) {
    drawEmptyState(
      doc,
      "No supplier follow-up letters were generated for this period.",
      startY,
      pageW
    );
    return;
  }

  autoTable(doc, {
    ...tableDefaults(),
    startY,
    head: [["#", "Supplier Name", "Supplier GSTIN", "Invoice #", "Action", "Date"]],
    body: rows.map((row, i) => [
      String(i + 1),
      row.supplier_name?.trim() || "—",
      row.supplier_gstin || "—",
      row.invoice_numbers || "—",
      row.action || "—",
      formatRule37ActionTimeIst(row.date),
    ]),
  });
}

/** Build the Rule 37 compliance PDF and return a Blob for download. */
export async function buildRule37CompliancePdfBlob(
  data: Rule37CompliancePdfData
): Promise<Blob> {
  const { jsPDF } = await import("jspdf");
  const autoTable = (await import("jspdf-autotable")).default;

  const doc = new jsPDF({ unit: "mm", format: "a4", compress: true });
  const pageW = doc.internal.pageSize.getWidth();
  const pageH = doc.internal.pageSize.getHeight();

  // Page 1 — Cover
  drawCoverPage(doc, data, pageW, pageH);

  // Page 2 — Executive Summary
  doc.addPage();
  let y = drawSectionHeader(doc, "Executive Summary", CONTENT_TOP, pageW);
  y = drawSummaryBoxes(doc, data.summary, y, pageW);

  doc.setFont("helvetica", "normal");
  doc.setFontSize(9);
  doc.setTextColor(...CHARCOAL);
  const summaryLines = doc.splitTextToSize(
    buildExecutiveSummary(data.summary),
    pageW - MARGIN * 2
  );
  doc.text(summaryLines, MARGIN, y + 4);

  y = y + 4 + summaryLines.length * 4.5 + 6;
  doc.setDrawColor(...BORDER_GREY);
  doc.setLineWidth(0.2);
  doc.line(MARGIN, y, pageW - MARGIN, y);
  y += 8;

  doc.setFont("helvetica", "bold");
  doc.setFontSize(11);
  doc.setTextColor(...CHARCOAL);
  doc.text("Action History", MARGIN, y);
  y += 5;
  renderActionHistoryTable(doc, autoTable, data.action_history, y);

  // Page 3 — Pending Invoices
  doc.addPage();
  y = drawSectionHeader(
    doc,
    "Invoices Requiring Immediate Action",
    CONTENT_TOP,
    pageW
  );
  y = drawSubtitle(doc, "Sorted by reversal deadline — most urgent first", y);
  renderPendingTable(doc, autoTable, data.pending_invoices, y);

  // Page 4 — ITC Secured
  doc.addPage();
  y = drawSectionHeader(
    doc,
    "ITC Secured — Supplier Payments Confirmed",
    CONTENT_TOP,
    pageW
  );
  renderSecuredTable(doc, autoTable, data.secured_invoices, y);

  // Page 5 — ITC Reversed
  doc.addPage();
  y = drawSectionHeader(doc, "ITC Reversed", CONTENT_TOP, pageW);
  renderReversedTable(doc, autoTable, data.reversed_invoices, y);

  // Page 6 — Supplier Follow-up Log
  doc.addPage();
  y = drawSectionHeader(doc, "Supplier Follow-up Activity", CONTENT_TOP, pageW);
  renderFollowupTable(doc, autoTable, data.followup_log, y);

  const totalPages = doc.getNumberOfPages();
  for (let p = 2; p <= totalPages; p++) {
    doc.setPage(p);
    drawHeader(doc, pageW);
    drawFooter(doc, pageW, p, totalPages);
  }

  return doc.output("blob");
}
