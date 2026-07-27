/** Pure helpers for the CA-facing IMS Action panel.
 *
 * No React / no network — mirror of GSTR-3B offsetConfirmLogic pattern.
 * Run tests: npx --yes tsx --test components/reconcile/imsActionLogic.test.ts
 */

export type ImsRecommendedAction = "accept" | "reject" | "hold";

export type ImsWritebackOutcome = "idle" | "pending" | "confirmed" | "failed";

export type ImsInvoiceRecommendation = {
  invoice_id: string;
  supplier_gstin: string;
  invoice_number: string;
  invoice_date?: string | null;
  supplier_name?: string | null;
  category: string;
  ims_status: string;
  recommended_action: ImsRecommendedAction;
  confidence_score: number;
  reason_codes: string[];
  human_readable_why: string;
  amount_paise?: number | null;
  section?: string;
  writeback_payload?: Record<string, unknown> | null;
  match_confidence?: number | null;
};

export type ImsRecommendationsResponse = {
  available: boolean;
  reason?: string | null;
  run_id?: string | null;
  period?: string | null;
  gstin?: string | null;
  source?: string;
  high_confidence_accept_count: number;
  invoice_count: number;
  invoices: ImsInvoiceRecommendation[];
};

export type ImsRowState = {
  invoiceId: string;
  /** CA-chosen action (may differ from recommendation). */
  chosenAction: ImsRecommendedAction;
  selected: boolean;
  whyExpanded: boolean;
  writeback: ImsWritebackOutcome;
  writebackError?: string | null;
};

export type ImsConfirmSteps = {
  reviewed: boolean;
  typedCount: string;
  holdProgressMs: number;
};

export const IMS_HOLD_MS = 2000;
export const HIGH_CONFIDENCE_ACCEPT_MIN = 0.85;

export const EMPTY_IMS_CONFIRM_STEPS: ImsConfirmSteps = {
  reviewed: false,
  typedCount: "",
  holdProgressMs: 0,
};

export function isHighConfidenceAccept(
  inv: Pick<ImsInvoiceRecommendation, "recommended_action" | "confidence_score">
): boolean {
  return (
    inv.recommended_action === "accept" &&
    inv.confidence_score >= HIGH_CONFIDENCE_ACCEPT_MIN
  );
}

export function isOverride(
  recommended: ImsRecommendedAction | string | null | undefined,
  chosen: ImsRecommendedAction | string
): boolean {
  if (!recommended) return true;
  return (
    String(recommended).trim().toLowerCase() !==
    String(chosen).trim().toLowerCase()
  );
}

export function submitMode(
  recommended: ImsRecommendedAction | string | null | undefined,
  chosen: ImsRecommendedAction | string
): "confirm_recommendation" | "override" {
  return isOverride(recommended, chosen)
    ? "override"
    : "confirm_recommendation";
}

/** Map CA hold → GSTN pending for display/copy only. */
export function caActionLabel(action: ImsRecommendedAction): string {
  switch (action) {
    case "accept":
      return "Accept";
    case "reject":
      return "Reject";
    case "hold":
      return "Hold";
  }
}

export function buildConfirmationSummary(
  action: ImsRecommendedAction,
  count: number
): string {
  const verb =
    action === "accept"
      ? "Accepting"
      : action === "reject"
        ? "Rejecting"
        : "Holding";
  const noun = count === 1 ? "invoice" : "invoices";
  return `${verb} ${count} ${noun}`;
}

export function parseTypedCount(raw: string): number | null {
  const cleaned = String(raw || "")
    .replace(/,/g, "")
    .replace(/\s/g, "")
    .trim();
  if (!cleaned) return null;
  const n = Number(cleaned);
  if (!Number.isFinite(n) || !Number.isInteger(n)) return null;
  return n;
}

export function typedCountMatchesExpected(
  typed: string,
  expected: number
): boolean {
  const parsed = parseTypedCount(typed);
  if (parsed == null) return false;
  return parsed === expected;
}

export function canStartImsHold(
  steps: ImsConfirmSteps,
  expectedCount: number
): boolean {
  return (
    steps.reviewed && typedCountMatchesExpected(steps.typedCount, expectedCount)
  );
}

export function isImsHoldComplete(
  steps: ImsConfirmSteps,
  holdMs: number = IMS_HOLD_MS
): boolean {
  return steps.holdProgressMs >= holdMs;
}

export function resetImsConfirmSteps(): ImsConfirmSteps {
  return { ...EMPTY_IMS_CONFIRM_STEPS };
}

export function initRowStates(
  invoices: ImsInvoiceRecommendation[]
): Map<string, ImsRowState> {
  const map = new Map<string, ImsRowState>();
  for (const inv of invoices) {
    map.set(inv.invoice_id, {
      invoiceId: inv.invoice_id,
      chosenAction: inv.recommended_action,
      selected: false,
      whyExpanded: false,
      writeback: "idle",
    });
  }
  return map;
}

export function selectHighConfidenceAccepts(
  invoices: ImsInvoiceRecommendation[],
  rows: Map<string, ImsRowState>
): Map<string, ImsRowState> {
  const next = new Map(rows);
  for (const inv of invoices) {
    const row = next.get(inv.invoice_id);
    if (!row) continue;
    if (isHighConfidenceAccept(inv)) {
      next.set(inv.invoice_id, {
        ...row,
        selected: true,
        chosenAction: "accept",
      });
    }
  }
  return next;
}

export function clearSelection(
  rows: Map<string, ImsRowState>
): Map<string, ImsRowState> {
  const next = new Map(rows);
  Array.from(next.entries()).forEach(([id, row]) => {
    next.set(id, { ...row, selected: false });
  });
  return next;
}

export function selectedRows(
  invoices: ImsInvoiceRecommendation[],
  rows: Map<string, ImsRowState>
): Array<{ inv: ImsInvoiceRecommendation; row: ImsRowState }> {
  const out: Array<{ inv: ImsInvoiceRecommendation; row: ImsRowState }> = [];
  for (const inv of invoices) {
    const row = rows.get(inv.invoice_id);
    if (row?.selected) out.push({ inv, row });
  }
  return out;
}

/**
 * Bulk confirm requires a single chosen action across the selection.
 * Mixed actions must be confirmed individually or re-selected.
 */
export function uniformSelectedAction(
  selected: Array<{ row: ImsRowState }>
): ImsRecommendedAction | null {
  if (selected.length === 0) return null;
  const first = selected[0].row.chosenAction;
  for (const s of selected) {
    if (s.row.chosenAction !== first) return null;
  }
  return first;
}

export function overrideCountInSelection(
  selected: Array<{ inv: ImsInvoiceRecommendation; row: ImsRowState }>
): number {
  return selected.filter(({ inv, row }) =>
    isOverride(inv.recommended_action, row.chosenAction)
  ).length;
}

/** Dual-status poll → per-invoice writeback state. */
export function writebackOutcomeFromPoll(poll: {
  is_complete: boolean;
  has_errors: boolean;
  status_cd?: string | null;
  outcome?: string | null;
}): ImsWritebackOutcome {
  if (poll.outcome === "confirmed" || poll.outcome === "failed" || poll.outcome === "pending") {
    return poll.outcome;
  }
  if (!poll.is_complete) return "pending";
  if (poll.has_errors) return "failed";
  if (poll.status_cd === "P") return "confirmed";
  return "failed";
}

export function applyWritebackOutcome(
  rows: Map<string, ImsRowState>,
  invoiceIds: string[],
  outcome: ImsWritebackOutcome,
  error?: string | null
): Map<string, ImsRowState> {
  const next = new Map(rows);
  for (const id of invoiceIds) {
    const row = next.get(id);
    if (!row) continue;
    next.set(id, {
      ...row,
      writeback: outcome,
      writebackError: error ?? null,
      selected: outcome === "confirmed" ? false : row.selected,
    });
  }
  return next;
}

export function unavailableHint(reason: string | null | undefined): string {
  switch (reason) {
    case "no_reconcile_payload":
      return "Recommendations unavailable — this run has no reconcile payload yet. This does not mean there are zero IMS invoices.";
    case "gstn_not_connected":
      return "Recommendations unavailable — connect GSTN (OTP) to load live IMS invoices. This does not mean the queue is empty.";
    case "no_ims_candidates":
      return "Recommendations unavailable — IMS candidates could not be assembled for this run.";
    case "not_wired":
      return "Recommendations unavailable — IMS recommendation API is not reachable yet. This does not mean a confirmed zero.";
    default:
      return reason
        ? `Recommendations unavailable (${reason}). This does not mean a confirmed zero.`
        : "Recommendations unavailable. This does not mean a confirmed zero.";
  }
}
