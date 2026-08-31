/**
 * DRC-01B Part B response draft scaffold.
 *
 * Reason labels match Form GST DRC-01B Part B (rule 88C) as notified —
 * not invented categories. Scaffold only: no portal submit / ARN validation.
 */

import { pdfBytesToBlob } from "@/lib/download";
import { formatINR } from "@/lib/format";
import type { Gstr1TieOut } from "@/lib/gstr1Reconcile";

/** Portal Part B “Brief Reasons for Difference” (Form GST DRC-01B). */
export type Drc01bReasonCategory =
  | "excess_liability_earlier_periods"
  | "earlier_period_txns_now_declared"
  | "gstr1_incorrect_will_amend"
  | "advances_reporting_mistake"
  | "any_other";

export type Drc01bReasonOption = {
  id: Drc01bReasonCategory;
  /** Exact / near-exact Form Part B label shown in the selector. */
  label: string;
  /** Editable starter for the Part B “Details (Mandatory)” narrative. */
  narrativeStub: string;
};

/**
 * Five notified Part B reasons (plus DRC-03 payment as a separate Part B
 * sub-part A on the portal — handled via optional DRC-03 fields, not as a
 * reason radio).
 *
 * Wording aligned to Form GST DRC-01B Part B / GSTN advisory.
 */
export const DRC01B_REASON_OPTIONS: Drc01bReasonOption[] = [
  {
    id: "excess_liability_earlier_periods",
    label:
      "Excess Liability paid in earlier tax periods in FORM GSTR-3B",
    narrativeStub:
      "The differential liability for the intimation period is attributable to excess tax liability already paid in FORM GSTR-3B of earlier tax period(s). Kindly adjust / consider the earlier excess payment against the present difference. Supporting workings of earlier-period excess payment are available on request.",
  },
  {
    id: "earlier_period_txns_now_declared",
    label:
      "Some transactions of earlier tax period which could not be declared in the FORM GSTR-1/IFF of the said tax period but in respect of which tax has already been paid in FORM GSTR-3B of the said tax period and which have now been declared in FORM GSTR-1/IFF of the tax period under consideration",
    narrativeStub:
      "Certain outward supplies pertaining to an earlier tax period could not be declared in FORM GSTR-1/IFF of that period. Tax on those supplies was already paid in FORM GSTR-3B of the earlier period; the invoices have now been declared in FORM GSTR-1/IFF of the period under consideration, creating an apparent liability mismatch. Invoice-wise particulars can be furnished if required.",
  },
  {
    id: "gstr1_incorrect_will_amend",
    label:
      "FORM GSTR-1/IFF filed with incorrect details and will be amended in next tax period (including typographical errors, wrong tax rates, etc.)",
    narrativeStub:
      "FORM GSTR-1/IFF for the period was filed with incorrect details (e.g. typographical errors / wrong tax rates / incorrect values). The incorrect particulars will be amended in the next eligible tax period through the applicable amendment tables. The liability as correctly reflected in FORM GSTR-3B Table 3.1(a) should be considered for this period.",
  },
  {
    id: "advances_reporting_mistake",
    label:
      "Mistake in reporting of advances received and adjusted against invoices",
    narrativeStub:
      "The difference arises from a mistake in reporting of advances received and/or adjusted against invoices (advance liability vs invoice adjustment timing). Correct reporting will be aligned in subsequent returns / amendments as applicable. Working of advances received and adjusted is available on request.",
  },
  {
    id: "any_other",
    label: "Any other reasons",
    narrativeStub:
      "The difference between liability as per FORM GSTR-1/IFF and FORM GSTR-3B for the period is explained as follows: [please specify facts, invoice/period references, and supporting position].",
  },
];

export type Drc01bTaxHeadKey = "igst" | "cgst" | "sgst" | "cess" | "total_tax";

export type Drc01bLiabilityRow = {
  key: Drc01bTaxHeadKey;
  label: string;
  gstr1Rupees: number;
  gstr3bRupees: number;
  diffRupees: number;
};

export type Drc03DraftFields = {
  paid: boolean | null;
  arn: string;
  date: string;
  amount: string;
};

function paiseToRupees(paise: unknown): number {
  const n = Number(paise);
  if (!Number.isFinite(n)) return 0;
  return n / 100;
}

export function buildDrc01bLiabilityRows(tieOut: Gstr1TieOut): Drc01bLiabilityRow[] {
  const g1 = tieOut.gstr1 || {};
  const g3 = tieOut.gstr3b || {};
  const heads: { key: Drc01bTaxHeadKey; label: string; g1Key: string; g3Key: string }[] =
    [
      { key: "igst", label: "IGST", g1Key: "igst_paise", g3Key: "igst_paise" },
      { key: "cgst", label: "CGST", g1Key: "cgst_paise", g3Key: "cgst_paise" },
      { key: "sgst", label: "SGST", g1Key: "sgst_paise", g3Key: "sgst_paise" },
      { key: "cess", label: "CESS", g1Key: "cess_paise", g3Key: "cess_paise" },
      {
        key: "total_tax",
        label: "Total tax",
        g1Key: "total_tax_paise",
        g3Key: "total_tax_paise",
      },
    ];
  return heads.map((h) => {
    const gstr1Rupees = paiseToRupees(g1[h.g1Key]);
    const gstr3bRupees = paiseToRupees(g3[h.g3Key]);
    return {
      key: h.key,
      label: h.label,
      gstr1Rupees,
      gstr3bRupees,
      diffRupees: gstr1Rupees - gstr3bRupees,
    };
  });
}

export function getDrc01bReasonOption(
  id: Drc01bReasonCategory | ""
): Drc01bReasonOption | undefined {
  if (!id) return undefined;
  return DRC01B_REASON_OPTIONS.find((o) => o.id === id);
}

function formatSignedInr(amount: number): string {
  if (Math.abs(amount) < 0.005) return formatINR(0);
  const sign = amount > 0 ? "+" : "−";
  return `${sign}${formatINR(Math.abs(amount))}`;
}

function formatLetterDate(isoOrEmpty: string): string {
  if (!isoOrEmpty.trim()) return "—";
  const d = new Date(isoOrEmpty);
  if (Number.isNaN(d.getTime())) return isoOrEmpty;
  return d.toLocaleDateString("en-IN", {
    day: "numeric",
    month: "short",
    year: "numeric",
  });
}

export function buildDrc01bReplyDraft(opts: {
  clientName: string;
  clientGstin: string;
  retPeriod: string;
  rows: Drc01bLiabilityRow[];
  reasonCategory: Drc01bReasonCategory | "";
  narrative: string;
  drc03: Drc03DraftFields;
}): string {
  const {
    clientName,
    clientGstin,
    retPeriod,
    rows,
    reasonCategory,
    narrative,
    drc03,
  } = opts;

  const today = new Date().toLocaleDateString("en-IN", {
    day: "numeric",
    month: "long",
    year: "numeric",
  });

  const reason = getDrc01bReasonOption(reasonCategory);
  const reasonLabel = reason?.label || "(not selected — select a portal reason before filing)";

  const tableLines = [
    "Tax head | GSTR-1 declared (agg.) | GSTR-3B Table 3.1(a) declared | Difference (GSTR-1 − 3B)",
    "---------|------------------------|--------------------------------|---------------------------",
    ...rows.map(
      (r) =>
        `${r.label} | ${formatINR(r.gstr1Rupees)} | ${formatINR(r.gstr3bRupees)} | ${formatSignedInr(r.diffRupees)}`
    ),
  ].join("\n");

  let drc03Block: string;
  if (drc03.paid === true) {
    drc03Block = [
      "Part B — A. Differential liability paid through FORM GST DRC-03: Yes",
      `ARN: ${drc03.arn.trim() || "—"}`,
      `Date of payment / filing: ${formatLetterDate(drc03.date)}`,
      `Amount (₹): ${drc03.amount.trim() || "—"}`,
      "(Enter and validate this ARN on the GST portal Part B; this draft does not validate ARNs.)",
    ].join("\n");
  } else if (drc03.paid === false) {
    drc03Block =
      "Part B — A. Differential liability paid through FORM GST DRC-03: No (reason explanation only).";
  } else {
    drc03Block =
      "Part B — A. Differential liability paid through FORM GST DRC-03: (not indicated — complete on portal if payment was made).";
  }

  const narrativeText =
    narrative.trim() ||
    "(Add mandatory Part B details / explanation — portal allows up to 500 characters.)";

  return `Date: ${today}

DRAFT — Form GST DRC-01B Part B reply
(Intimation of difference in liability reported in statement of outward supplies and that reported in return — Rule 88C)

Taxpayer: ${clientName || "—"}
GSTIN: ${clientGstin || "—"}
Return period: ${retPeriod || "—"}

────────────────────────────────────────
PART A SUMMARY (from ReconDesk tie-out — for drafting only)
────────────────────────────────────────
Figures below are ReconDesk aggregates of GSTR-1 invoice-level outward supplies versus GSTR-3B Table 3.1(a) declared outward taxable supplies for the period. They are NOT payment/cash-ledger proof.

IMPORTANT — declared vs paid:
GST portal DRC-01B Part A compares liability as per GSTR-1/IFF with liability paid through GSTR-3B. This draft uses Table 3.1(a) declared outward supply totals from the uploaded returns. Before filing Part B on the portal, verify the official Part A figures and actual tax paid (electronic credit/cash ledger / DRC-03) independently.

${tableLines}

────────────────────────────────────────
PART B — REPLY DRAFT (scaffold; not submitted)
────────────────────────────────────────
${drc03Block}

B. Brief reason for difference (portal option):
${reasonLabel}

Details (mandatory on portal — editable draft):
${narrativeText}

────────────────────────────────────────
This is a system-generated DRC-01B Part B reply draft for review by the authorised person / CA. It is not filed with the GST portal. It does not constitute legal advice. Confirm portal Part A amounts, reason selection, DRC-03 ARN (if any), and narrative before submitting on gst.gov.in.`;
}

export function drc01bPdfFilename(clientGstin: string, retPeriod: string): string {
  const gstin = (clientGstin || "taxpayer").replace(/[^A-Za-z0-9-]/g, "") || "taxpayer";
  const period = (retPeriod || "period").replace(/[^A-Za-z0-9-]/g, "") || "period";
  return `drc-01b-part-b-draft-${gstin}-${period}.pdf`;
}

/** Build a PDF blob from draft text (client-only; dynamic import) — same pattern as follow-up letter. */
export async function buildDrc01bReplyPdfBlob(
  letterBody: string,
  disclaimer: string
): Promise<Blob> {
  const { jsPDF } = await import("jspdf");
  const doc = new jsPDF({ unit: "mm", format: "a4" });
  const margin = 18;
  const lineHeight = 5.5;
  const pageHeight = doc.internal.pageSize.getHeight();
  const maxWidth = doc.internal.pageSize.getWidth() - margin * 2;
  const fullText = `${letterBody}\n\n${disclaimer}`;

  doc.setFont("helvetica", "normal");
  doc.setFontSize(10);
  const lines = doc.splitTextToSize(fullText, maxWidth);
  let y = margin;
  for (let i = 0; i < lines.length; i++) {
    if (y > pageHeight - margin) {
      doc.addPage();
      y = margin;
    }
    doc.text(lines[i], margin, y);
    y += lineHeight;
  }
  const pdfBytes = doc.output("arraybuffer");
  return pdfBytesToBlob(pdfBytes);
}
