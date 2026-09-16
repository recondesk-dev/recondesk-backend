/**
 * Domain logic & helpers for Phase 5.5B: Revalidation UX.
 * Pure TypeScript functions ensuring deterministic status mapping,
 * tax safety UX invariants, and maker-checker compliance.
 */

export type RevalUxStatus =
  | "NONE"
  | "PENDING"
  | "REVALIDATING"
  | "CLEARED"
  | "PERSISTS"
  | "CHANGED"
  | "ERROR"
  | "NOT_REVALIDATED";

export const REVALIDATION_STATUS_LABELS: Record<RevalUxStatus, string> = {
  NONE: "Not revalidated",
  PENDING: "Revalidation queued",
  REVALIDATING: "Revalidation in progress",
  CLEARED: "Exception cleared",
  PERSISTS: "Exception persists",
  CHANGED: "Exception changed",
  ERROR: "Revalidation failed",
  NOT_REVALIDATED: "Could not revalidate",
};

/**
 * Derives the canonical UX status from work item fields and event metadata.
 */
export function deriveEffectiveRevalStatus(
  item: {
    revalidation_status?: string | null;
    revalidation_result?: string | null;
  },
  latestEvent?: {
    event_type?: string;
    metadata?: Record<string, any>;
  }
): RevalUxStatus {
  const rawStatus = (item.revalidation_status || "").trim().toUpperCase();
  const rawResult = (item.revalidation_result || "").trim().toUpperCase();

  if (rawStatus === "REVALIDATING") {
    return "REVALIDATING";
  }
  if (rawStatus === "PENDING") {
    return "PENDING";
  }
  if (rawStatus === "ERROR") {
    return "ERROR";
  }
  if (rawStatus === "REVALIDATED") {
    if (rawResult === "CLEARED") return "CLEARED";
    if (rawResult === "PERSISTS") return "PERSISTS";
    if (rawResult === "CHANGED") return "CHANGED";
    if (rawResult === "NOT_REVALIDATED") return "NOT_REVALIDATED";
    if (rawResult === "ERROR") return "ERROR";

    // Event metadata fallback
    const evRes = (latestEvent?.metadata?.revalidation_result || "").trim().toUpperCase();
    if (evRes === "CLEARED") return "CLEARED";
    if (evRes === "PERSISTS") return "PERSISTS";
    if (evRes === "CHANGED") return "CHANGED";
    if (evRes === "NOT_REVALIDATED") return "NOT_REVALIDATED";
    if (evRes === "ERROR") return "ERROR";

    return "CLEARED";
  }

  // If rawResult is populated directly
  if (rawResult === "CLEARED") return "CLEARED";
  if (rawResult === "PERSISTS") return "PERSISTS";
  if (rawResult === "CHANGED") return "CHANGED";
  if (rawResult === "NOT_REVALIDATED") return "NOT_REVALIDATED";
  if (rawResult === "ERROR") return "ERROR";

  return "NONE";
}

export function getRevalidationBadgeStyle(status: RevalUxStatus): {
  badgeBg: string;
  badgeText: string;
  badgeBorder: string;
  dotColor: string;
} {
  switch (status) {
    case "CLEARED":
      return {
        badgeBg: "bg-emerald-50",
        badgeText: "text-emerald-800",
        badgeBorder: "border-emerald-200",
        dotColor: "bg-emerald-600",
      };
    case "PERSISTS":
      return {
        badgeBg: "bg-rose-50",
        badgeText: "text-rose-800",
        badgeBorder: "border-rose-200",
        dotColor: "bg-rose-600",
      };
    case "CHANGED":
      return {
        badgeBg: "bg-amber-50",
        badgeText: "text-amber-800",
        badgeBorder: "border-amber-200",
        dotColor: "bg-amber-600",
      };
    case "REVALIDATING":
      return {
        badgeBg: "bg-blue-50",
        badgeText: "text-blue-800 animate-pulse",
        badgeBorder: "border-blue-200",
        dotColor: "bg-blue-600",
      };
    case "PENDING":
      return {
        badgeBg: "bg-indigo-50",
        badgeText: "text-indigo-800",
        badgeBorder: "border-indigo-200",
        dotColor: "bg-indigo-600",
      };
    case "ERROR":
      return {
        badgeBg: "bg-red-50",
        badgeText: "text-red-800",
        badgeBorder: "border-red-200",
        dotColor: "bg-red-600",
      };
    case "NOT_REVALIDATED":
      return {
        badgeBg: "bg-gray-100",
        badgeText: "text-gray-800",
        badgeBorder: "border-gray-200",
        dotColor: "bg-gray-500",
      };
    case "NONE":
    default:
      return {
        badgeBg: "bg-gray-50",
        badgeText: "text-gray-600",
        badgeBorder: "border-gray-200",
        dotColor: "bg-gray-400",
      };
  }
}

/**
 * Sanitizes technical error messages to prevent leaking stack traces, SQL strings, or credentials.
 */
export function sanitizeTechnicalReason(raw?: string | null): string {
  if (!raw) return "An unexpected technical error occurred during evaluation.";
  const clean = raw
    .replace(/SELECT .* FROM .*/gi, "[redacted query]")
    .replace(/password|secret|bearer|token/gi, "[redacted]")
    .replace(/\b([a-zA-Z0-9_-]+)\.py:[0-9]+/g, "")
    .trim();
  if (clean.length > 200) {
    return clean.slice(0, 197) + "…";
  }
  return clean || "Revalidation failed due to an unexpected technical exception.";
}

/**
 * Safe, professional explanation for why a work item could not be revalidated.
 * Guaranteed never to confuse NOT_REVALIDATED with PERSISTS.
 */
export function getNotRevalidatedExplanation(
  reasonCode?: string | null,
  comparisonReason?: string | null
): string {
  const code = (reasonCode || "").trim().toUpperCase();
  if (code === "NO_ELIGIBLE_AUTHORITATIVE_RUN") {
    return "No eligible completed authoritative reconciliation run was found for this client and period.";
  }
  if (code === "STALE_TARGET_SUPERSEDED") {
    return "A newer authoritative reconciliation run was completed before persistence; the earlier comparison was rejected to prevent stale overwrites.";
  }
  if (
    code === "NON_REVALIDATABLE_EXCEPTION" ||
    code === "SEC_17_5" ||
    code === "TIME_BARRED_16_4"
  ) {
    return "Statutory exception requires professional CA determination and cannot be cleared by automated vendor revalidation.";
  }
  if (code === "AMBIGUOUS_INVOICE_IDENTITY" || code === "MULTIPLE_MATCHES") {
    return "Multiple matching invoice records were detected in the authoritative outcome; manual reconciliation review is required.";
  }
  if (code === "MISSING_INVOICE_NUMBER") {
    return "Invoice number is missing or invalid on the source work item.";
  }
  return comparisonReason || "ReconDesk could not establish an unambiguous authoritative comparison.";
}

/**
 * Evaluates whether requesting revalidation is permitted.
 */
export function canRequestRevalidation(
  status: RevalUxStatus,
  exceptionType?: string | null
): { allowed: boolean; reason?: string } {
  const exc = (exceptionType || "").toUpperCase();
  if (exc === "SEC_17_5" || exc === "TIME_BARRED_16_4") {
    return {
      allowed: false,
      reason:
        "Statutory exceptions under Sec 17(5) or Sec 16(4) require CA manual adjudication and cannot be revalidated automatically.",
    };
  }
  if (status === "PENDING") {
    return { allowed: false, reason: "Revalidation is already queued for evaluation." };
  }
  if (status === "REVALIDATING") {
    return { allowed: false, reason: "Revalidation is currently being evaluated." };
  }
  return { allowed: true };
}

/**
 * Determines whether retry is permitted after error or failed comparison.
 */
export function canRetryRevalidation(status: RevalUxStatus): boolean {
  return status === "ERROR" || status === "NOT_REVALIDATED";
}

/**
 * Checks whether maker-checker review is mandatory.
 */
export function isMakerCheckerRequired(item: {
  is_blocking?: boolean;
  status?: string;
}): boolean {
  return Boolean(item.is_blocking || item.status === "READY_FOR_REVIEW");
}

/**
 * Resolves authoritative tax difference after revalidation without manufacturing zero.
 * Returns null if no authoritative value was supplied by backend.
 */
export function resolveTaxDiffAfterPaise(
  item?: { tax_diff_after?: number | null } | null,
  latestEvent?: { metadata?: Record<string, any> } | null
): number | null {
  if (
    latestEvent?.metadata?.tax_diff_after != null &&
    Number.isFinite(Number(latestEvent.metadata.tax_diff_after))
  ) {
    return Number(latestEvent.metadata.tax_diff_after);
  }
  if (item?.tax_diff_after != null && Number.isFinite(Number(item.tax_diff_after))) {
    return Number(item.tax_diff_after);
  }
  return null;
}

/**
 * Formats tax difference after revalidation.
 * - Displays formatted authoritative value when present (₹0.00 for 0, or formatted INR).
 * - Displays "—" when absent/null.
 * Never manufactures ₹0.00 merely because an item is CLEARED.
 */
export function formatTaxDiffAfter(taxDiffAfterPaise: number | null | undefined): string {
  if (taxDiffAfterPaise == null || !Number.isFinite(taxDiffAfterPaise)) {
    return "—";
  }
  if (taxDiffAfterPaise === 0) {
    return "₹0.00";
  }
  const inr = taxDiffAfterPaise / 100;
  return `₹${inr.toLocaleString("en-IN", {
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  })}`;
}
