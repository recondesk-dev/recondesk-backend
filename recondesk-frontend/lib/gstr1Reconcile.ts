/**
 * Types + client for POST /api/gstr1-reconcile (sales-side GSTR-1 check).
 */

import { apiFetch, isApiError } from "@/lib/api";

export const GSTR1_RECONCILE_STORAGE_KEY = "recondesk.gstr1_reconcile.result";

export type Gstr1MismatchType =
  | "G1M1_MISSING_INVOICE"
  | "G1M2_EXTRA_INVOICE"
  | "G1M3_AMOUNT_MISMATCH"
  | "G1M4_WRONG_CLASSIFICATION"
  | "G1M5_RATE_MISMATCH"
  | "G1M6_PERIOD_MISMATCH"
  | "G1M7_INVALID_GSTIN"
  | string;

export type Gstr1DecisionFields = {
  mismatch_type?: Gstr1MismatchType;
  mismatch_severity?: string;
  decision_what?: string | null;
  decision_why?: string | null;
  decision_next?: string | null;
  decision_rule?: string | null;
  decision_confidence?: string | null;
  recipient_gstin?: string | null;
  invoice_number?: string | null;
  [key: string]: unknown;
};

export type Gstr1SanitisedRecord = {
  invoice_number?: string | null;
  invoice_number_normalized?: string | null;
  invoice_date?: string | null;
  gstin?: string | null;
  recipient_gstin?: string | null;
  recipient_name?: string | null;
  taxable_amount_paise?: number | null;
  total_tax_paise?: number | null;
  total_amount_paise?: number | null;
  invoice_value_paise?: number | null;
  igst_paise?: number | null;
  cgst_paise?: number | null;
  sgst_paise?: number | null;
  section?: string | null;
  [key: string]: unknown;
};

export type Gstr1MatchedRow = Gstr1DecisionFields & {
  sr_record: Gstr1SanitisedRecord;
  gstr1_record: Gstr1SanitisedRecord | null;
  match_level?: number | null;
  confidence?: number | null;
  requires_human_review?: boolean;
  discrepancies?: string[];
  compared_fields?: string[];
  identity_confidence?: string | null;
  financial_status?: string | null;
  review_reason?: string | null;
};

export type Gstr1UnmatchedRow = Gstr1DecisionFields & {
  record: Gstr1SanitisedRecord;
};

export type Gstr1TieOutVariance = {
  field: string;
  gstr1: string;
  gstr3b: string;
  diff: string;
  direction: "over" | "under" | string;
};

export type Gstr1TieOut = {
  ret_period?: string;
  is_clean?: boolean;
  variance_count?: number;
  gstr1_record_count?: number;
  gstr1?: Record<string, number>;
  gstr3b?: Record<string, number>;
  gstr1_by_rate?: Record<string, Record<string, number>>;
  variances?: Gstr1TieOutVariance[];
  mismatch_decisions?: Gstr1DecisionFields[];
};

export type Gstr1ParseDiagnostics = {
  sr?: {
    total_rows?: number;
    valid_rows?: number;
    skipped_rows?: number;
    source_software?: string;
    warnings?: string[];
    errors?: string[];
    sheets_used?: string[];
    sheets_skipped?: string[];
  };
  gstr1?: {
    filing_gstin?: string;
    filing_period?: string;
    total_parsed?: number;
    total_skipped?: number;
    section_counts?: Record<string, number>;
    sections_present?: string[];
    skip_breakdown_labeled?: unknown[];
  };
};

export type Gstr1ReconcileSummary = {
  sr_total_records: number;
  gstr1_total_records: number;
  /** Aggregate rows (HSN/nil/advances) excluded from invoice matching. */
  gstr1_metadata_record_count?: number;
  matched_count: number;
  unmatched_sr_count: number;
  unmatched_gstr1_count: number;
  mismatch_count: number;
  tie_out_clean: boolean;
  tie_out_variance_count: number;
};

export type Gstr1ReconcileResult = {
  success: boolean;
  elapsed_seconds?: number;
  summary: Gstr1ReconcileSummary;
  matched: Gstr1MatchedRow[];
  unmatched_sr: Gstr1UnmatchedRow[];
  unmatched_gstr1: Gstr1UnmatchedRow[];
  mismatches: Gstr1DecisionFields[];
  tie_out: Gstr1TieOut;
  parse_diagnostics?: Gstr1ParseDiagnostics;
  /** Client-side metadata attached after upload */
  meta?: {
    created_at: string;
    sales_register_filename?: string;
    gstr1_filename?: string;
    gstr3b_filename?: string;
    filing_period?: string | null;
    client_name?: string | null;
  };
};

export type Gstr1ReconcileUploadInput = {
  salesRegisterFile: File;
  gstr1JsonFile: File;
  gstr3bJsonFile: File;
  gstr1FilingPeriod?: string | null;
  token: string;
};

export function paiseToRupees(paise: number | null | undefined): number {
  if (paise == null || Number.isNaN(Number(paise))) return 0;
  return Number(paise) / 100;
}

export function recordGstin(rec: Gstr1SanitisedRecord | null | undefined): string {
  const raw = rec?.gstin || rec?.recipient_gstin || "";
  return String(raw).trim();
}

export function recordInvoiceNumber(
  rec: Gstr1SanitisedRecord | null | undefined
): string {
  return String(
    rec?.invoice_number || rec?.invoice_number_normalized || "?"
  ).trim();
}

export function recordAmountRupees(
  rec: Gstr1SanitisedRecord | null | undefined
): number {
  if (!rec) return 0;
  const paise =
    rec.taxable_amount_paise ??
    rec.total_amount_paise ??
    rec.invoice_value_paise ??
    0;
  return paiseToRupees(paise);
}

/** Matched rows that need human review → Review Required tab. */
export function filterReviewRequired(matched: Gstr1MatchedRow[]): Gstr1MatchedRow[] {
  return matched.filter((row) => {
    if (row.requires_human_review) return true;
    const conf = row.confidence;
    if (typeof conf === "number" && conf < 90) return true;
    const label = String(row.decision_confidence || "").toUpperCase();
    if (label === "MEDIUM" || label === "LOW") return true;
    return Boolean(row.discrepancies && row.discrepancies.length > 0);
  });
}

export function mismatchTypeShort(type: string | undefined): string {
  if (!type) return "—";
  for (const code of [
    "G1M1",
    "G1M2",
    "G1M3",
    "G1M4",
    "G1M5",
    "G1M6",
    "G1M7",
  ] as const) {
    if (type.includes(code)) return code;
  }
  return type;
}

export function countMismatchesByType(
  mismatches: Gstr1DecisionFields[]
): Record<string, number> {
  const counts: Record<string, number> = {};
  for (const m of mismatches) {
    const code = mismatchTypeShort(m.mismatch_type);
    counts[code] = (counts[code] || 0) + 1;
  }
  return counts;
}

export async function runGstr1Reconcile(
  input: Gstr1ReconcileUploadInput
): Promise<Gstr1ReconcileResult> {
  const form = new FormData();
  form.append("sales_register_file", input.salesRegisterFile);
  form.append("gstr1_json", input.gstr1JsonFile);
  form.append("gstr3b_json", input.gstr3bJsonFile);
  if (input.gstr1FilingPeriod?.trim()) {
    form.append("gstr1_filing_period", input.gstr1FilingPeriod.trim());
  }

  try {
    const result = await apiFetch<Gstr1ReconcileResult>("/api/gstr1-reconcile", {
      method: "POST",
      token: input.token,
      body: form,
      timeoutMs: 180_000,
      directBackend: true,
    });
    return {
      ...result,
      meta: {
        created_at: new Date().toISOString(),
        sales_register_filename: input.salesRegisterFile.name,
        gstr1_filename: input.gstr1JsonFile.name,
        gstr3b_filename: input.gstr3bJsonFile.name,
        filing_period: input.gstr1FilingPeriod ?? null,
      },
    };
  } catch (err) {
    if (isApiError(err)) throw err;
    throw err;
  }
}

export function persistGstr1Result(result: Gstr1ReconcileResult): void {
  if (typeof window === "undefined") return;
  sessionStorage.setItem(GSTR1_RECONCILE_STORAGE_KEY, JSON.stringify(result));
}

export function loadGstr1Result(): Gstr1ReconcileResult | null {
  if (typeof window === "undefined") return null;
  try {
    const raw = sessionStorage.getItem(GSTR1_RECONCILE_STORAGE_KEY);
    if (!raw) return null;
    return JSON.parse(raw) as Gstr1ReconcileResult;
  } catch {
    return null;
  }
}

export function clearGstr1Result(): void {
  if (typeof window === "undefined") return;
  sessionStorage.removeItem(GSTR1_RECONCILE_STORAGE_KEY);
}
