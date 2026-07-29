/** Rule 37 summary and action history types. */

import { formatINR } from "@/lib/format";

export type Rule37SummaryStats = {
  total_itc_at_risk: number;
  itc_saved: number;
  itc_reversed: number;
  pending_action: number;
  /** Past-180 invoices with blank payment_status (not in confirmed at-risk). */
  pending_verification_count?: number;
  /** Upper-bound ITC if those unverified invoices turn out unpaid. */
  pending_verification_exposure?: number;
  claimed_invoice_count?: number;
  payment_status_known_count?: number;
  payment_status_unknown_count?: number;
  /** False for older runs that predate coverage metrics. */
  coverage_available?: boolean;
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

/** Coverage line for the Rule 37 summary card / section header. */
export function formatRule37CoverageLine(summary: Rule37SummaryStats): string | null {
  if (!summary.coverage_available) return null;
  const known = summary.payment_status_known_count ?? 0;
  const claimed = summary.claimed_invoice_count ?? 0;
  if (claimed <= 0) return "No ITC-claimed matched invoices in this period.";
  return `Payment status known for ${known} of ${claimed} claimed invoices`;
}

/**
 * Empty-state copy when the at-risk list is empty — distinguishes verified-clean
 * from "never had payment data."
 */
export function formatRule37EmptyStateMessage(
  summary: Rule37SummaryStats | null | undefined
): string {
  if (!summary) {
    return "No confirmed Rule 37 at-risk invoices for this period.";
  }
  const pendingCount = summary.pending_verification_count ?? 0;
  const unknown = summary.payment_status_unknown_count ?? 0;
  const claimed = summary.claimed_invoice_count ?? 0;
  const coverageOk = Boolean(summary.coverage_available);

  if (pendingCount > 0 || (coverageOk && unknown > 0)) {
    const n = pendingCount > 0 ? pendingCount : unknown;
    return (
      `No confirmed Rule 37 at-risk invoices, but payment status is unknown ` +
      `for ${n} invoice${n === 1 ? "" : "s"} — verify manually or upload payment dates.`
    );
  }
  if (coverageOk && claimed > 0 && unknown === 0) {
    return (
      `No Rule 37 warnings for this period — payment status confirmed for all ` +
      `${claimed} claimed invoice${claimed === 1 ? "" : "s"}.`
    );
  }
  if (coverageOk && claimed === 0) {
    return "No ITC-claimed matched invoices subject to Rule 37 in this period.";
  }
  return "No confirmed Rule 37 at-risk invoices for this period.";
}

/** Short sublabel under the section header ₹0 badge. */
export function formatRule37HeaderCoverageSublabel(
  summary: Rule37SummaryStats | null | undefined
): string | undefined {
  if (!summary) return undefined;
  const line = formatRule37CoverageLine(summary);
  if (line) return line;
  const pending = summary.pending_verification_count ?? 0;
  if (pending > 0) {
    return `${pending} invoice${pending === 1 ? "" : "s"} need payment verification`;
  }
  return undefined;
}
