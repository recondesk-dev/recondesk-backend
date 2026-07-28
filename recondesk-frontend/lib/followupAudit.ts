/** Supplier follow-up audit log types and display helpers. */

export type SupplierFollowupAuditRow = {
  id: string;
  run_id: string;
  tax_period: string;
  supplier_gstin: string;
  supplier_name_display: string | null;
  template_type: string;
  status: string;
  generated_by: string;
  generated_by_name: string;
  generated_at: string;
  invoice_numbers_display?: string;
  /** Full letter text when persisted; null for legacy audit rows. */
  letter_body?: string | null;
};

export function formatFollowupAuditTimeIst(iso: string): string {
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return "—";
  return d.toLocaleString("en-IN", { timeZone: "Asia/Kolkata" });
}

const TEMPLATE_LABELS: Record<string, string> = {
  wrongful_itc_single: "Wrongful ITC (single)",
  wrongful_itc_bulk: "Wrongful ITC (bulk)",
};

const STATUS_LABELS: Record<string, string> = {
  generated: "Generated",
  downloaded: "Downloaded",
  copied: "Copied",
};

export function formatFollowupTemplateType(value: string): string {
  return TEMPLATE_LABELS[value] ?? value;
}

export function formatFollowupAuditStatus(value: string): string {
  return STATUS_LABELS[value] ?? value;
}

export function followupHistoryExportFilename(clientGstin: string): string {
  const safe =
    (clientGstin || "client").replace(/[^A-Za-z0-9]/g, "").toUpperCase() ||
    "client";
  return `followup-history-${safe}.xlsx`;
}
