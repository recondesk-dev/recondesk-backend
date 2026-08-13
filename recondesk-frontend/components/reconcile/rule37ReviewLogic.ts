export type Rule37ReviewActionStatus =
  | "resolved"
  | "acknowledged"
  | "pending_review"
  | "rejected";

export type Rule37ReviewMetadata = {
  reason?: string;
  bill_ref?: string;
  party?: string;
  supplier_name?: string;
  invoice_number?: string;
  record_id?: string;
  run_id?: string;
  bill_ref_score?: number;
  party_sim?: number;
  party_gate_min?: number;
  amount_paid?: number;
  payment_date?: string;
};

export type Rule37ReviewRow = {
  id: string;
  invoice_number: string;
  supplier_gstin: string;
  amount: number;
  rule37_action_status?: Rule37ReviewActionStatus | null;
  rule37_action_id?: string | null;
  rule37_review_metadata?: Rule37ReviewMetadata | null;
};

export function isPendingReviewRow(
  row: Rule37ReviewRow,
  localStatus?: Rule37ReviewActionStatus
): boolean {
  const status = localStatus ?? row.rule37_action_status;
  return status === "pending_review";
}

export function formatPartyConfidenceWarning(
  meta?: Rule37ReviewMetadata | null
): string {
  if (!meta) return "Manual review required: low confidence match";
  const party = meta.party || "Unknown Party";
  const supplier = meta.supplier_name || "Unknown Supplier";
  const simPercent =
    meta.party_sim != null ? Math.round(meta.party_sim * 100) : 0;
  const gatePercent = Math.round((meta.party_gate_min || 0.82) * 100);
  return `Party name '${party}' matched '${supplier}' at ${simPercent}% confidence — below auto-settle threshold (${gatePercent}%)`;
}

export function buildResolvePayload(
  actionId: string,
  status: "resolved" | "rejected"
) {
  return {
    url: `/api/tally-sync/review/${encodeURIComponent(actionId)}/resolve`,
    method: "POST",
    body: { status },
  };
}
