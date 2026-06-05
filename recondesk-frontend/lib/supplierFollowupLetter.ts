/** Supplier follow-up letter — types and draft builder (ITC at risk). */

import { pdfBytesToBlob } from "@/lib/download";
import { formatINR } from "@/lib/format";

export type FollowupTemplateType = "wrongful_itc_single" | "wrongful_itc_bulk";

export type FollowupAuditStatus = "generated" | "downloaded" | "copied";

/** Frozen reconciliation facts sent to audit API (not edited letter text). */
export type FollowupInvoiceSnapshotItem = {
  record_id: string;
  supplier_gstin: string;
  invoice_number: string;
  invoice_date: string;
  amount: number;
  decision_what: string | null;
  decision_why: string | null;
  decision_next: string | null;
  trade_name: string | null;
};

export type FollowupAuditPayload = {
  supplier_gstin: string;
  record_ids: string[];
  tax_period: string;
  invoice_snapshot: FollowupInvoiceSnapshotItem[];
  template_type: FollowupTemplateType;
  status: FollowupAuditStatus;
  supplier_name_display?: string | null;
};

export type RiskRowForFollowup = {
  id: string;
  supplier_gstin: string;
  trade_name?: string | null;
  invoice_number: string;
  invoice_date: string;
  amount: number;
  decision_what: string | null;
  decision_why: string | null;
  decision_next: string | null;
};

export function buildInvoiceSnapshot(
  rows: RiskRowForFollowup[]
): FollowupInvoiceSnapshotItem[] {
  return rows.map((row) => ({
    record_id: row.id,
    supplier_gstin: row.supplier_gstin.trim().toUpperCase(),
    invoice_number: row.invoice_number,
    invoice_date: row.invoice_date,
    amount: row.amount,
    decision_what: row.decision_what,
    decision_why: row.decision_why,
    decision_next: row.decision_next,
    trade_name: row.trade_name?.trim() || null,
  }));
}

export function defaultSupplierDisplayName(
  rows: RiskRowForFollowup[],
  editedName: string
): string {
  const trimmed = editedName.trim();
  if (trimmed) return trimmed;
  const fromRow = rows.map((r) => r.trade_name?.trim()).find(Boolean);
  if (fromRow) return fromRow;
  const gstin = rows[0]?.supplier_gstin?.trim();
  return gstin ? `M/s ${gstin}` : "Supplier";
}

function formatLetterDate(iso: string): string {
  if (!iso) return "—";
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return iso;
  return d.toLocaleDateString("en-IN", {
    day: "numeric",
    month: "short",
    year: "numeric",
  });
}

export function buildFollowupLetterDraft(opts: {
  clientName: string;
  clientGstin: string;
  taxPeriod: string;
  supplierDisplayName: string;
  supplierGstin: string;
  snapshot: FollowupInvoiceSnapshotItem[];
}): string {
  const {
    clientName,
    clientGstin,
    taxPeriod,
    supplierDisplayName,
    supplierGstin,
    snapshot,
  } = opts;

  const today = new Date().toLocaleDateString("en-IN", {
    day: "numeric",
    month: "long",
    year: "numeric",
  });

  const intro =
    snapshot.length === 1
      ? `We refer to invoice ${snapshot[0].invoice_number} dated ${formatLetterDate(snapshot[0].invoice_date)}, recorded in our purchase register for tax period ${taxPeriod}. The invoice is not reflecting in our GSTR-2B, which affects our eligible input tax credit (ITC).`
      : `We refer to the following invoice(s) recorded in our purchase register for tax period ${taxPeriod} that are not reflecting in our GSTR-2B, which affects our eligible input tax credit (ITC):`;

  const invoiceBlock =
    snapshot.length === 1
      ? ""
      : "\n\n" +
        snapshot
          .map(
            (inv, i) =>
              `${i + 1}. Invoice ${inv.invoice_number} | Date: ${formatLetterDate(inv.invoice_date)} | Amount: ${formatINR(inv.amount)}`
          )
          .join("\n");

  const first = snapshot[0];
  const reason =
    first?.decision_what?.trim() ||
    "Invoice in purchase register but not appearing in recipient GSTR-2B.";
  const action =
    first?.decision_next?.trim() ||
    "Please file or amend your GSTR-1 return so that the invoice(s) appear in our GSTR-2B at the earliest.";

  return `Date: ${today}

To,
${supplierDisplayName}
GSTIN: ${supplierGstin}

Subject: Request to reflect invoice(s) in GSTR-1 / GSTR-2B — ${clientName} (${clientGstin}) — Period ${taxPeriod}

Dear Sir/Madam,

${intro}${invoiceBlock}

Reason (reconciliation): ${reason}

Requested action: ${action}

We request your cooperation to resolve this at the earliest so that ITC can be availed in accordance with law.

Thanking you,

For ${clientName}
GSTIN: ${clientGstin}

---
This is a system-generated follow-up draft. Please review before sending.
This letter is generated for informational and communication purposes. It does not constitute legal advice.`;
}

export function templateTypeForRowCount(count: number): FollowupTemplateType {
  return count === 1 ? "wrongful_itc_single" : "wrongful_itc_bulk";
}

function sanitizePdfFilenamePart(value: string, fallback: string): string {
  return value.replace(/[^A-Za-z0-9-]/g, "") || fallback;
}

export function followupPdfFilename(
  supplierGstin: string,
  taxPeriod: string
): string {
  const gstin = sanitizePdfFilenamePart(supplierGstin || "", "supplier");
  const period = sanitizePdfFilenamePart(taxPeriod || "", "period");
  return `supplier-followup-${gstin}-${period}.pdf`;
}

/** Build a PDF blob from letter text (client-only; dynamic import). */
export async function buildFollowupLetterPdfBlob(
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
  doc.setFontSize(11);
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
