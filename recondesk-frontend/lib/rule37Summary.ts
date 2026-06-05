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
  mark_paid: "Mark Paid",
  reverse_itc: "Reverse ITC",
};

export function formatRule37ActionLabel(
  action: Rule37ActionHistoryRow["action"]
): string {
  return ACTION_LABELS[action] ?? action;
}

export function formatRule37TdsDeducted(
  tds: number | null | undefined
): string {
  if (tds == null || tds <= 0) return "—";
  return formatINR(tds);
}

export function formatRule37TotalSettled(row: Rule37ActionHistoryRow): string {
  const tds = row.tds_deducted ?? 0;
  if (tds > 0 && row.total_settled != null) {
    return formatINR(row.total_settled);
  }
  if (row.amount_paid != null) return formatINR(row.amount_paid);
  if (row.total_settled != null) return formatINR(row.total_settled);
  return "—";
}

/** PDF / compact payment line for mark-paid actions. */
export function formatRule37PaymentPdfLine(row: Rule37ActionHistoryRow): string {
  const tds = row.tds_deducted ?? 0;
  if (row.action !== "mark_paid") return "—";
  const cash = row.amount_paid ?? (row.total_settled != null ? row.total_settled - tds : null);
  if (cash == null) return "—";
  if (tds > 0 && row.total_settled != null) {
    return `Cash: ${formatINR(cash)} + TDS: ${formatINR(tds)} = Total: ${formatINR(row.total_settled)} (CA verified)`;
  }
  return formatINR(cash);
}
