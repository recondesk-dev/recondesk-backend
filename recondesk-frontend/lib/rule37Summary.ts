/** Rule 37 summary and action history types. */

import { formatINR } from "@/lib/format";

export type Rule37SummaryStats = {
  total_itc_at_risk: number;
  itc_saved: number;
  itc_reversed: number;
  pending_action: number;
};

export type Rule37ActionHistoryRow = {
  id: string;
  invoice_number: string;
  supplier_gstin: string;
  amount: number;
  action: "mark_paid" | "reverse_itc";
  created_at: string;
  generated_by: string;
  generated_by_name: string;
  amount_paid?: number | null;
  tds_deducted?: number;
  total_settled?: number | null;
  remaining_unpaid_amount?: number | null;
  payment_coverage?: "full" | "partial" | null;
};

export type Rule37SummaryResponse = {
  summary: Rule37SummaryStats;
  action_history: Rule37ActionHistoryRow[];
};

export function formatRule37ActionTimeIst(iso: string): string {
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return "—";
  return d.toLocaleString("en-IN", { timeZone: "Asia/Kolkata" });
}

const ACTION_LABELS: Record<Rule37ActionHistoryRow["action"], string> = {
  mark_paid: "Marked as Settled",
  reverse_itc: "Reverse ITC",
};

export function formatRule37ActionLabel(
  action: Rule37ActionHistoryRow["action"]
): string {
  return ACTION_LABELS[action] ?? action;
}

export function formatRule37OptionalInr(
  value: number | null | undefined
): string {
  if (value == null) return "—";
  return formatINR(value);
}

export function formatRule37NetPaid(
  value: number | null | undefined
): string {
  if (value == null) return "—";
  return formatINR(value);
}

export function formatRule37StatutoryDeduction(
  value: number | null | undefined
): string {
  if (value == null || value <= 0) return "—";
  return formatINR(value);
}

export function formatRule37SettlementConsidered(
  row: Rule37ActionHistoryRow
): string {
  if (row.action !== "mark_paid") return "—";
  if (row.total_settled != null) return formatINR(row.total_settled);
  if (row.amount_paid != null) {
    return formatINR(row.amount_paid + (row.tds_deducted ?? 0));
  }
  return "—";
}

export function formatRule37RemainingUnpaid(
  row: Rule37ActionHistoryRow
): string {
  if (row.action !== "mark_paid") return "—";
  if (row.remaining_unpaid_amount != null) {
    return formatINR(row.remaining_unpaid_amount);
  }
  return "—";
}

/** PDF / compact settlement line for mark-settled actions. */
export function formatRule37PaymentPdfLine(row: Rule37ActionHistoryRow): string {
  if (row.action !== "mark_paid") return "—";
  const net = row.amount_paid;
  const statutory = row.tds_deducted ?? 0;
  const settled =
    row.total_settled ??
    (net != null ? Math.round((net + statutory) * 100) / 100 : null);
  if (net == null || settled == null) return "—";
  if (statutory > 0) {
    return `Net: ${formatINR(net)} + Statutory: ${formatINR(statutory)} = Settlement: ${formatINR(settled)} (CA verified)`;
  }
  return formatINR(net);
}
