/** Rule 37 summary and action history types. */

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
