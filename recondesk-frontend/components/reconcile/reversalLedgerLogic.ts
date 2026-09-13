/**
 * Domain logic, status formatting, statutory boundaries, and evidence payload builders
 * for the GSTR-3B Table 4 Reversal & Reclaim Ledger frontend.
 */

import type {
  ReversalStatusType,
  StatutoryTemporaryReasonType,
  ReversalLedgerEntryDto,
  ReversalConditionFulfillPayload,
} from "@/lib/api";

export interface ReversalStatusMeta {
  code: ReversalStatusType;
  label: string;
  badgeBg: string;
  badgeText: string;
  badgeBorder: string;
  dotColor: string;
  description: string;
}

export const REVERSAL_STATUS_META: Record<ReversalStatusType, ReversalStatusMeta> = {
  OPEN: {
    code: "OPEN",
    label: "Reversal recorded — condition pending",
    badgeBg: "bg-amber-50",
    badgeText: "text-amber-800",
    badgeBorder: "border-amber-200",
    dotColor: "bg-amber-500",
    description: "Reversal is active in Table 4(B)(2). Statutory reclaim condition is not yet satisfied.",
  },
  CONDITION_FULFILLED: {
    code: "CONDITION_FULFILLED",
    label: "Condition verified — awaiting reclaim authorization",
    badgeBg: "bg-blue-50",
    badgeText: "text-blue-800",
    badgeBorder: "border-blue-200",
    dotColor: "bg-blue-500",
    description: "Fulfillment evidence has been recorded. Requires Chartered Accountant authorization before reclaim.",
  },
  RECLAIM_AUTHORIZED: {
    code: "RECLAIM_AUTHORIZED",
    label: "Reclaim authorized",
    badgeBg: "bg-emerald-50",
    badgeText: "text-emerald-800",
    badgeBorder: "border-emerald-200",
    dotColor: "bg-emerald-500",
    description: "Authorized by CA. Ready to be reclaimed into an active GSTR-3B return.",
  },
  PARTIALLY_RECLAIMED: {
    code: "PARTIALLY_RECLAIMED",
    label: "Partially reclaimed",
    badgeBg: "bg-indigo-50",
    badgeText: "text-indigo-800",
    badgeBorder: "border-indigo-200",
    dotColor: "bg-indigo-500",
    description: "Portion of the reversal has been reclaimed into earlier periods. Remaining balance is available.",
  },
  FULLY_RECLAIMED: {
    code: "FULLY_RECLAIMED",
    label: "Fully reclaimed",
    badgeBg: "bg-gray-100",
    badgeText: "text-gray-700",
    badgeBorder: "border-gray-300",
    dotColor: "bg-gray-500",
    description: "Entire reversed ITC has been reclaimed. Ledger entry is closed.",
  },
  NON_RECLAIMABLE: {
    code: "NON_RECLAIMABLE",
    label: "Non-reclaimable",
    badgeBg: "bg-rose-50",
    badgeText: "text-rose-800",
    badgeBorder: "border-rose-200",
    dotColor: "bg-rose-500",
    description: "Permanent or non-reclaimable reversal. Excluded from reclaim lifecycle.",
  },
};

export const STATUTORY_REASON_LABELS: Record<StatutoryTemporaryReasonType, string> = {
  RULE_37_NON_PAYMENT: "Rule 37 — Non-payment to supplier within 180 days",
  RULE_37A_SUPPLIER_NON_FILING: "Rule 37A — Supplier GSTR-3B non-filing",
  SECTION_16_2_B_NOT_RECEIVED: "Section 16(2)(b) — Goods/services not received",
  SECTION_16_2_C_SUPPLIER_TAX_CONDITION: "Section 16(2)(c) — Supplier tax payment condition",
  OTHER_TEMPORARY: "Other Temporary Statutory Reversal",
  OPENING_BALANCE: "Opening Balance / Prior Period Transition",
};

/** Formats integer paise into a standard decimal Rupee number. */
export function paiseToRupees(paise: number | undefined | null): number {
  if (paise == null || isNaN(paise)) return 0;
  return Number((paise / 100).toFixed(2));
}

/** Formats Rupee decimal input into integer paise. */
export function rupeesToPaise(rupees: number | string | undefined | null): number {
  if (rupees == null || rupees === "") return 0;
  const num = typeof rupees === "string" ? parseFloat(rupees) : rupees;
  if (isNaN(num)) return 0;
  return Math.round(num * 100);
}

/** Returns whether an entry can have its statutory condition fulfilled. */
export function canFulfillCondition(entry: Pick<ReversalLedgerEntryDto, "is_reclaimable" | "status">): boolean {
  if (!entry.is_reclaimable) return false;
  return entry.status === "OPEN";
}

/** Returns whether an entry is eligible for CA authorization. Rejects if still OPEN. */
export function canAuthorizeReclaim(entry: Pick<ReversalLedgerEntryDto, "is_reclaimable" | "status">): boolean {
  if (!entry.is_reclaimable) return false;
  return entry.status === "CONDITION_FULFILLED";
}

/** Returns whether an entry can be reclaimed into an active target run. */
export function canExecuteReclaim(
  entry: Pick<ReversalLedgerEntryDto, "is_reclaimable" | "status">,
  targetRun?: { is_locked?: boolean; status?: string }
): boolean {
  if (!entry.is_reclaimable) return false;
  if (entry.status !== "RECLAIM_AUTHORIZED" && entry.status !== "PARTIALLY_RECLAIMED") {
    return false;
  }
  if (targetRun) {
    if (Boolean(targetRun.is_locked)) return false;
    if (String(targetRun.status || "").toUpperCase() === "FINAL") return false;
  }
  return true;
}

/**
 * Hard statutory boundary:
 * Table 4(D)(2) (Section 16(4) time-barred, PoS-restricted) and
 * Table 4(B)(1) (Section 17(5) blocked, Rules 38, 42, 43)
 * can NEVER expose a reclaim action or be added to a reclaim ledger.
 */
export function isReclaimAllowedForTable4Cell(cell: string): boolean {
  const norm = (cell || "").trim().toUpperCase();
  if (norm === "4D2" || norm === "4B1") return false;
  if (norm === "4B2") return true;
  return false;
}

export interface TaxHeadBalanceValidation {
  isValid: boolean;
  errorMessage?: string;
  excessTaxHead?: string;
}

export interface TaxHeadPaise {
  igst_paise: number;
  cgst_paise: number;
  sgst_paise: number;
  cess_paise: number;
}

/**
 * Pre-flight validation for requested reclaim amounts against backend-provided available balances.
 * Prevents exceeding available tax-head limits before network submission.
 */
export function validateReclaimAmounts(
  requested: TaxHeadPaise,
  available: TaxHeadPaise
): TaxHeadBalanceValidation {
  if (
    requested.igst_paise < 0 ||
    requested.cgst_paise < 0 ||
    requested.sgst_paise < 0 ||
    requested.cess_paise < 0
  ) {
    return { isValid: false, errorMessage: "Reclaim amounts cannot be negative." };
  }

  const totalRequested =
    requested.igst_paise +
    requested.cgst_paise +
    requested.sgst_paise +
    requested.cess_paise;

  if (totalRequested <= 0) {
    return { isValid: false, errorMessage: "Total reclaim amount must be greater than ₹0.00." };
  }

  if (requested.igst_paise > available.igst_paise) {
    return {
      isValid: false,
      excessTaxHead: "IGST",
      errorMessage: `Requested IGST exceeds available balance of ₹${paiseToRupees(available.igst_paise).toLocaleString("en-IN", { minimumFractionDigits: 2 })}.`,
    };
  }
  if (requested.cgst_paise > available.cgst_paise) {
    return {
      isValid: false,
      excessTaxHead: "CGST",
      errorMessage: `Requested CGST exceeds available balance of ₹${paiseToRupees(available.cgst_paise).toLocaleString("en-IN", { minimumFractionDigits: 2 })}.`,
    };
  }
  if (requested.sgst_paise > available.sgst_paise) {
    return {
      isValid: false,
      excessTaxHead: "SGST",
      errorMessage: `Requested SGST exceeds available balance of ₹${paiseToRupees(available.sgst_paise).toLocaleString("en-IN", { minimumFractionDigits: 2 })}.`,
    };
  }
  if (requested.cess_paise > available.cess_paise) {
    return {
      isValid: false,
      excessTaxHead: "Cess",
      errorMessage: `Requested Cess exceeds available balance of ₹${paiseToRupees(available.cess_paise).toLocaleString("en-IN", { minimumFractionDigits: 2 })}.`,
    };
  }

  return { isValid: true };
}

/** Pre-flight check for required statutory evidence based on reason. */
export function validateEvidencePayload(
  reason: StatutoryTemporaryReasonType,
  payload: ReversalConditionFulfillPayload
): { isValid: boolean; errorMessage?: string } {
  if (reason === "RULE_37_NON_PAYMENT") {
    if (!payload.payment_reference || payload.payment_reference.trim().length === 0) {
      return { isValid: false, errorMessage: "Payment reference (UTR / Cheque / Txn ID) is required for Rule 37." };
    }
    if (!payload.payment_date || payload.payment_date.trim().length === 0) {
      return { isValid: false, errorMessage: "Payment date is required for Rule 37." };
    }
  } else if (reason === "RULE_37A_SUPPLIER_NON_FILING") {
    if (!payload.supplier_filing_arn || payload.supplier_filing_arn.trim().length === 0) {
      return { isValid: false, errorMessage: "Supplier GSTR-3B Filing ARN is required for Rule 37A." };
    }
    if (!payload.supplier_filing_date || payload.supplier_filing_date.trim().length === 0) {
      return { isValid: false, errorMessage: "Supplier GSTR-3B filing date is required for Rule 37A." };
    }
  } else if (reason === "SECTION_16_2_B_NOT_RECEIVED") {
    if (!payload.receipt_evidence_ref || payload.receipt_evidence_ref.trim().length === 0) {
      return { isValid: false, errorMessage: "Receipt evidence reference (GRN / Delivery Challan) is required for Section 16(2)(b)." };
    }
    if (!payload.receipt_date || payload.receipt_date.trim().length === 0) {
      return { isValid: false, errorMessage: "Goods / services receipt date is required for Section 16(2)(b)." };
    }
  }
  return { isValid: true };
}

/** Generates a collision-resistant idempotency key for reclaim submissions. */
export function generateReclaimIdempotencyKey(ledgerId: string, targetRunId: string): string {
  const ts = Date.now();
  const rand = Math.random().toString(36).substring(2, 8);
  return `rcm-${ledgerId.substring(0, 8)}-${targetRunId.substring(0, 8)}-${ts}-${rand}`;
}
