export const RECONCILE_TABLE_PAGE_SIZE_OPTIONS = [25, 50, 100, 250] as const;

export const DEFAULT_RECONCILE_TABLE_PAGE_SIZE = 50;

export type ReconcileTablePageSize =
  (typeof RECONCILE_TABLE_PAGE_SIZE_OPTIONS)[number];

export const RECONCILE_PAGE_SIZE_STORAGE_KEYS = {
  matched: "recondesk.reconcile.matchedPageSize",
  review_required: "recondesk.reconcile.reviewRequiredPageSize",
  itc: "recondesk.reconcile.itcPageSize",
  risk: "recondesk.reconcile.riskPageSize",
  rule37: "recondesk.reconcile.rule37PageSize",
  section17: "recondesk.reconcile.section17PageSize",
  followup: "recondesk.reconcile.followupPageSize",
  itc_on_hold: "recondesk.reconcile.itcOnHoldPageSize",
} as const;

export function isValidReconcileTablePageSize(
  size: number
): size is ReconcileTablePageSize {
  return RECONCILE_TABLE_PAGE_SIZE_OPTIONS.includes(
    size as ReconcileTablePageSize
  );
}

export function readStoredReconcileTablePageSize(storageKey: string): number {
  if (typeof window === "undefined") return DEFAULT_RECONCILE_TABLE_PAGE_SIZE;
  const raw = localStorage.getItem(storageKey);
  const n = Number(raw);
  if (isValidReconcileTablePageSize(n)) {
    return n;
  }
  return DEFAULT_RECONCILE_TABLE_PAGE_SIZE;
}

export function persistReconcileTablePageSize(
  storageKey: string,
  size: number
): void {
  try {
    localStorage.setItem(storageKey, String(size));
  } catch {
    /* ignore quota / private mode */
  }
}
