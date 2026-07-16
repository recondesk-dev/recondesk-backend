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
  | "G1M8_INVOICE_SERIES_ISSUE"
  | "G1M9_HSN_RATE_ISSUE"
  | "G1M10_DOCUMENTS_ISSUED_SUMMARY"
  | "G1M11_AMENDMENT_REQUIRED"
  | string;

export type Gstr1aEligibility =
  | "eligible"
  | "not_eligible"
  | "review_required"
  | string;

export type Gstr1aWindowStatus =
  | "open"
  | "window_closed"
  | "expired"
  | "not_open"
  | "review_required"
  | string;

export type Gstr1aWindow = {
  status: Gstr1aWindowStatus;
  days_remaining: number | null;
  gstr3b_due_date?: string | null;
  gstr1_filed_date?: string | null;
  gstr3b_filed_date?: string | null;
  note?: string | null;
};

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
  /** GSTR-1A amendability for this mismatch rule. */
  eligibility?: Gstr1aEligibility | null;
  note?: string | null;
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
  prior_gstr1?: {
    filing_gstin?: string;
    filing_period?: string;
    total_parsed?: number;
    invoice_level_count?: number;
    section_counts?: Record<string, number>;
  } | null;
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
  /** G1M10 Table 13 series count. */
  documents_issued_series_count?: number;
  /** True when prior-period GSTR-1 was not uploaded (G1M11 skipped). */
  amendment_detection_skipped?: boolean;
  /** Count of invoices requiring Tables 9A/9B/9C amendments. */
  amendment_count?: number;
  gstr1_filed_date?: string | null;
  gstr3b_filed_date?: string | null;
  gstr1a_window?: Gstr1aWindow | null;
};

export type Gstr1DocumentsIssuedSeries = {
  document_type: string;
  document_type_label?: string;
  series_prefix: string;
  opening_number: string;
  closing_number: string;
  opening_seq?: number;
  closing_seq?: number;
  total_issued: number;
  cancelled: number | null;
  net_issued: number;
  span?: number;
  span_bounded?: boolean;
  expected_serial_count?: number | null;
};

export type Gstr1DocumentsIssuedByType = {
  document_type: string;
  document_type_label?: string;
  total_issued: number;
  cancelled: number | null;
  net_issued: number;
  series_count: number;
};

export type Gstr1DocumentsIssued = {
  source?: string;
  cancellations_determinable?: boolean;
  series?: Gstr1DocumentsIssuedSeries[];
  by_document_type?: Record<string, Gstr1DocumentsIssuedByType>;
  gstr1_doc_issue_present?: boolean;
  total_series?: number;
  total_documents_issued?: number;
};

export type Gstr1ReconcileResult = {
  success: boolean;
  elapsed_seconds?: number;
  summary: Gstr1ReconcileSummary;
  matched: Gstr1MatchedRow[];
  unmatched_sr: Gstr1UnmatchedRow[];
  unmatched_gstr1: Gstr1UnmatchedRow[];
  mismatches: Gstr1DecisionFields[];
  /** G1M10 Table 13 period-level documents issued summary. */
  documents_issued?: Gstr1DocumentsIssued;
  tie_out: Gstr1TieOut;
  parse_diagnostics?: Gstr1ParseDiagnostics;
  gstr1_filed_date?: string | null;
  gstr3b_filed_date?: string | null;
  /** Period-level GSTR-1A amendment window (shared across mismatches). */
  gstr1a_window?: Gstr1aWindow | null;
  /** Persisted run id when client_gstin_id was supplied on upload. */
  run_id?: string;
  client_gstin_id?: string;
  /** Client-side metadata attached after upload */
  meta?: {
    created_at: string;
    sales_register_filename?: string;
    gstr1_filename?: string;
    gstr3b_filename?: string;
    prior_gstr1_filename?: string;
    filing_period?: string | null;
    client_name?: string | null;
    client_gstin_id?: string | null;
  };
};

export type Gstr1RunListRow = {
  id: string;
  client_gstin_id: string;
  period?: string | null;
  status: string;
  run_summary?: Record<string, unknown> | null;
  created_by?: string | null;
  created_at: string;
  completed_at?: string | null;
};

export type Gstr1RunDetail = Gstr1RunListRow & {
  result_payload: Gstr1ReconcileResult;
};

export type Gstr1ReconcileUploadInput = {
  salesRegisterFile: File;
  gstr1JsonFile: File;
  gstr3bJsonFile: File;
  /** Optional prior-period GSTR-1 for Tables 9A/9B/9C amendment detection. */
  priorGstr1JsonFile?: File | null;
  gstr1FilingPeriod?: string | null;
  /** When set, backend persists the run for durable banner / revisit. */
  clientGstinId?: string | null;
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
    "G1M8",
    "G1M9",
    "G1M10",
    "G1M11",
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

/** True when a mismatch can be routed through GSTR-1A. */
export function isGstr1aEligible(
  m: Pick<Gstr1DecisionFields, "eligibility">
): boolean {
  return String(m.eligibility || "").toLowerCase() === "eligible";
}

export function filterGstr1aEligibleMismatches(
  mismatches: Gstr1DecisionFields[]
): Gstr1DecisionFields[] {
  return mismatches.filter(isGstr1aEligible);
}

/** Align period keys with backend ``normalise_action_period`` (prefer YYYY-MM). */
export function normalisePeriodKey(raw: string | null | undefined): string {
  const s = String(raw || "").trim();
  if (!s) return "";
  if (/^\d{4}-\d{2}$/.test(s)) return s;
  if (/^\d{6}$/.test(s)) return `${s.slice(2, 6)}-${s.slice(0, 2)}`;
  if (/^\d{4}-\d{2}-\d{2}/.test(s)) return s.slice(0, 7);
  return s;
}

/**
 * Resolve a display period for a mismatch.
 * Prefers explicit filing/invoice period fields, then invoice month, then run fallback.
 */
export function resolveMismatchPeriod(
  m: Gstr1DecisionFields,
  fallbackPeriod: string
): string {
  const filing = m.filing_period ?? m.period ?? m.invoice_period;
  if (filing != null && String(filing).trim()) {
    return normalisePeriodKey(String(filing)) || String(filing).trim();
  }
  const invDate = m.invoice_date;
  if (typeof invDate === "string" && invDate.length >= 7) {
    // YYYY-MM-DD → YYYY-MM
    if (/^\d{4}-\d{2}/.test(invDate)) return invDate.slice(0, 7);
  }
  const fb = normalisePeriodKey(fallbackPeriod) || String(fallbackPeriod || "").trim();
  return fb || "Unknown period";
}

export type Gstr1aPeriodGroup = {
  period: string;
  mismatches: Gstr1DecisionFields[];
};

/** Group GSTR-1A-eligible mismatches by period (stable period order). */
export function groupGstr1aEligibleByPeriod(
  mismatches: Gstr1DecisionFields[],
  fallbackPeriod: string
): Gstr1aPeriodGroup[] {
  const eligible = filterGstr1aEligibleMismatches(mismatches);
  const map = new Map<string, Gstr1DecisionFields[]>();
  for (const m of eligible) {
    const period = resolveMismatchPeriod(m, fallbackPeriod);
    const list = map.get(period);
    if (list) list.push(m);
    else map.set(period, [m]);
  }
  return Array.from(map.entries())
    .sort(([a], [b]) => a.localeCompare(b))
    .map(([period, rows]) => ({ period, mismatches: rows }));
}

/** Run-level period label used as fallback when grouping. */
export function gstr1RunPeriodLabel(result: Gstr1ReconcileResult): string {
  return (
    result.meta?.filing_period ||
    result.tie_out?.ret_period ||
    result.parse_diagnostics?.gstr1?.filing_period ||
    ""
  );
}

export async function runGstr1Reconcile(
  input: Gstr1ReconcileUploadInput
): Promise<Gstr1ReconcileResult> {
  const form = new FormData();
  form.append("sales_register_file", input.salesRegisterFile);
  form.append("gstr1_json", input.gstr1JsonFile);
  form.append("gstr3b_json", input.gstr3bJsonFile);
  if (input.priorGstr1JsonFile) {
    form.append("prior_gstr1_json", input.priorGstr1JsonFile);
  }
  if (input.gstr1FilingPeriod?.trim()) {
    form.append("gstr1_filing_period", input.gstr1FilingPeriod.trim());
  }
  if (input.clientGstinId?.trim()) {
    form.append("client_gstin_id", input.clientGstinId.trim());
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
        prior_gstr1_filename: input.priorGstr1JsonFile?.name,
        filing_period: input.gstr1FilingPeriod ?? null,
        client_gstin_id: input.clientGstinId ?? null,
      },
    };
  } catch (err) {
    if (isApiError(err)) throw err;
    throw err;
  }
}

export async function listGstr1Runs(
  token: string,
  params: { client_gstin_id: string; limit?: number; status?: string }
): Promise<Gstr1RunListRow[]> {
  const sp = new URLSearchParams();
  sp.set("client_gstin_id", params.client_gstin_id);
  if (params.limit != null) sp.set("limit", String(params.limit));
  if (params.status) sp.set("status", params.status);
  return apiFetch<Gstr1RunListRow[]>(`/api/gstr1-reconcile/runs?${sp}`, {
    token,
    directBackend: true,
  });
}

export async function getGstr1Run(
  token: string,
  runId: string
): Promise<Gstr1RunDetail> {
  return apiFetch<Gstr1RunDetail>(
    `/api/gstr1-reconcile/runs/${encodeURIComponent(runId)}`,
    { token, directBackend: true }
  );
}

export type Gstr1aPeriodAction = {
  id: string;
  run_id: string;
  period: string;
  status: string;
  filed_date?: string | null;
  note?: string | null;
  user_id?: string | null;
  created_at?: string | null;
  /** Present on PATCH response */
  acted_by?: string | null;
  acted_at?: string | null;
};

export async function listGstr1aFiledPeriods(
  token: string,
  runId: string
): Promise<Gstr1aPeriodAction[]> {
  return apiFetch<Gstr1aPeriodAction[]>(
    `/api/gstr1-reconcile/runs/${encodeURIComponent(runId)}/gstr1a-filed`,
    { token, directBackend: true }
  );
}

export async function markGstr1aPeriodFiled(
  token: string,
  runId: string,
  body: {
    period: string;
    confirmed: boolean;
    filed_date?: string | null;
    note?: string | null;
  }
): Promise<Gstr1aPeriodAction> {
  return apiFetch<Gstr1aPeriodAction>(
    `/api/gstr1-reconcile/runs/${encodeURIComponent(runId)}/gstr1a-filed`,
    {
      method: "PATCH",
      token,
      body: JSON.stringify(body),
      directBackend: true,
    }
  );
}

export async function loadGstr1ResultByRunId(
  token: string,
  runId: string
): Promise<Gstr1ReconcileResult | null> {
  try {
    const row = await getGstr1Run(token, runId);
    const payload = row.result_payload;
    if (!payload) return null;
    return {
      ...payload,
      run_id: row.id,
      client_gstin_id: row.client_gstin_id,
      meta: {
        ...(payload.meta || {}),
        created_at: row.created_at || payload.meta?.created_at || new Date().toISOString(),
        filing_period: row.period ?? payload.meta?.filing_period ?? null,
        client_gstin_id: row.client_gstin_id,
      },
    };
  } catch {
    return null;
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
