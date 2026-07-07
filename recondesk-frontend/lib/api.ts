/**
 * Typed API client for the FastAPI backend (Railway).
 * Base URL is read from NEXT_PUBLIC_API_URL.
 */

import type {
  Database,
  ReconciliationStatus,
  MatchStatus,
} from "@/lib/supabase/types";

const API_URL = (process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000").replace(
  /\/+$/,
  ""
);

/** Default timeout for short status polls (must stay well under Vercel's 300s limit). */
export const STATUS_POLL_REQUEST_TIMEOUT_MS = 10_000;

// ─── Re-export DB row types for convenience ───────────────────────────────────

export type ClientGstin =
  Database["public"]["Tables"]["client_gstins"]["Row"];
export type ReconciliationRun =
  Database["public"]["Tables"]["reconciliation_runs"]["Row"];
export type GstrRecord =
  Database["public"]["Tables"]["gstr_records"]["Row"];
export type PrRecord =
  Database["public"]["Tables"]["pr_records"]["Row"];
export type MismatchNote =
  Database["public"]["Tables"]["mismatch_notes"]["Row"];
export type TeamMemberRecord =
  Database["public"]["Tables"]["team_members"]["Row"];
export type UserProfile =
  Database["public"]["Tables"]["user_profiles"]["Row"];

/** Row shape from GET /api/team/members */
export interface TeamMemberListItem {
  id: string;
  member_user_id: string | null;
  full_name: string;
  email: string;
  role: string;
  joined_at: string | null;
  status: "active" | "pending";
  invite_expires_at: string | null;
}

/** Profile from GET `/api/v1/auth/me` (`auth.router` + `/me`; see `AUTH_ROUTER_PREFIX`). */
export interface AuthMeProfile {
  id: string;
  email?: string | null;
  full_name?: string | null;
  firm_name?: string | null;
  phone?: string | null;
  role: string;
  is_active?: boolean;
  created_at?: string | null;
  plan?: string | null;
  runs_used?: number | null;
  runs_limit?: number | null;
  free_runs_remaining?: number | null;
  runs_balance?: number | null;
  firm_city?: string | null;
  icai_membership_number?: string | null;
  firm_gstin?: string | null;
  onboarding_completed?: boolean | null;
}

export interface ProfileUpdatePayload {
  full_name: string;
  phone?: string | null;
  firm_name?: string | null;
  icai_membership_number?: string | null;
  firm_gstin?: string | null;
  firm_city?: string | null;
}

export type AcceptInviteResponse =
  | { status: "accepted"; redirect: string }
  | {
      status: "signup_required";
      redirect: string;
      email: string;
      role: string;
      token: string;
    };
export type Payment =
  Database["public"]["Tables"]["payments"]["Row"];

// ─── API-specific types ───────────────────────────────────────────────────────

export interface ApiError {
  detail: string;
  status: number;
}

export function isApiError(e: unknown): e is ApiError {
  return (
    typeof e === "object" &&
    e !== null &&
    "detail" in e &&
    "status" in e &&
    typeof (e as ApiError).detail === "string" &&
    typeof (e as ApiError).status === "number"
  );
}

export interface PaginatedResponse<T> {
  items: T[];
  total: number;
  page: number;
  page_size: number;
}

export interface UploadRunResponse {
  run_id: string;
  message: string;
}

export interface ReconciliationSummary {
  run_id: string;
  matched_count: number;
  missed_itc_count: number;
  wrongful_risk_count: number;
  total_gstr_itc_paise: number;
  matched_itc_paise: number;
  missed_itc_paise: number;
  wrongful_risk_paise: number;
}

export interface RecordWithStatus {
  record: GstrRecord | PrRecord;
  match_status: MatchStatus;
}

// ─── Core fetch wrapper ───────────────────────────────────────────────────────

function formatApiErrorDetail(raw: unknown, fallback: string): string {
  if (raw == null) return fallback;
  if (typeof raw === "string") return raw;
  if (Array.isArray(raw)) {
    return raw
      .map((item) =>
        typeof item === "object" && item && "msg" in item
          ? String((item as { msg: unknown }).msg)
          : JSON.stringify(item)
      )
      .join("; ");
  }
  return String(raw);
}

/** Strip accidental trailing slashes (e.g. `/api/foo/` → `/api/foo`). Root `/` unchanged. */
function normalizeApiPath(path: string): string {
  const p = path.trim();
  if (p.length <= 1) return p;
  return p.replace(/\/+$/, "");
}

/** Railway (or local) backend base — never routes through the Next.js `/api/reconcile` proxy. */
export function backendApiUrl(path: string): string {
  return `${API_URL}${normalizeApiPath(path)}`;
}

/** Resolve fetch URL — browser reconcile calls go through same-origin Next.js proxy. */
function resolveApiUrl(path: string, directBackend = false): string {
  const normalized = normalizeApiPath(path);
  if (directBackend) {
    return backendApiUrl(normalized);
  }
  if (
    typeof window !== "undefined" &&
    normalized.startsWith("/api/reconcile")
  ) {
    return normalized;
  }
  return backendApiUrl(normalized);
}

export async function apiFetch<T>(
  path: string,
  options: RequestInit & {
    token?: string;
    /** Always call Railway directly; required for run status polling. */
    directBackend?: boolean;
    /** Abort the request after this many ms (e.g. status polls). */
    timeoutMs?: number;
    cache?: RequestCache;
  } = {}
): Promise<T> {
  const {
    token,
    directBackend = false,
    timeoutMs,
    cache,
    ...fetchOptions
  } = options;

  const headers = new Headers();

  const incoming = fetchOptions.headers;
  if (incoming instanceof Headers) {
    incoming.forEach((value, key) => {
      if (value != null && value !== "") headers.set(key, value);
    });
  } else if (incoming && typeof incoming === "object") {
    for (const [key, value] of Object.entries(incoming)) {
      if (value != null && value !== "") headers.set(key, String(value));
    }
  }

  const isFormData =
    typeof FormData !== "undefined" && fetchOptions.body instanceof FormData;

  if (!isFormData && !headers.has("Content-Type")) {
    headers.set("Content-Type", "application/json");
  }

  const bearer = typeof token === "string" ? token.trim() : "";
  if (bearer) {
    headers.set("Authorization", `Bearer ${bearer}`);
  }

  const controller =
    timeoutMs != null && timeoutMs > 0 ? new AbortController() : null;
  const timeoutId =
    controller != null
      ? setTimeout(() => controller.abort(), timeoutMs)
      : undefined;

  let res: Response;
  try {
    res = await fetch(resolveApiUrl(path, directBackend), {
      ...fetchOptions,
      headers,
      signal: controller?.signal ?? fetchOptions.signal,
      ...(cache ? { cache: cache as RequestCache } : {}),
    });
  } catch (err) {
    if (controller?.signal.aborted) {
      throw {
        detail: "Request timed out",
        status: 408,
      } satisfies ApiError;
    }
    throw err;
  } finally {
    if (timeoutId != null) clearTimeout(timeoutId);
  }

  if (!res.ok) {
    let detail = `HTTP ${res.status}`;
    try {
      const json = (await res.json()) as { detail?: unknown };
      detail = formatApiErrorDetail(json.detail, detail);
    } catch {
      // Response body was not JSON
    }
    throw { detail, status: res.status } satisfies ApiError;
  }

  if (res.status === 204) return undefined as unknown as T;

  return res.json() as Promise<T>;
}

// ─── Client GSTINs ───────────────────────────────────────────────────────────

/** Builds `/api/clients` (no trailing slash) or `/api/clients/{segments…}`. */
function clientsApiPath(...segments: string[]): string {
  const cleaned = segments
    .map((s) => String(s).trim())
    .map((s) => s.replace(/^\/+|\/+$/g, ""))
    .filter((s) => s.length > 0);
  return "/api/clients" + (cleaned.length ? "/" + cleaned.join("/") : "");
}

export interface ClientCreatePayload {
  gstin: string;
  trade_name: string;
  legal_name?: string | null;
  contact_name?: string | null;
  contact_email?: string | null;
  contact_phone?: string | null;
  assigned_to?: string | null;
}

export const clientsApi = {
  list: (token: string) =>
    apiFetch<ClientGstin[]>(clientsApiPath(), { token }),

  get: (token: string, id: string) =>
    apiFetch<ClientGstin>(clientsApiPath(id), { token }),

  create: (token: string, data: ClientCreatePayload) =>
    apiFetch<ClientGstin & { gstin_verification_warning?: string }>(clientsApiPath(), {
      method: "POST",
      body: JSON.stringify(data),
      token,
    }),

  validateGstin: (token: string, gstin: string) =>
    apiFetch<
      | { valid: true; normalized: string; state: string }
      | { valid: false; error: string }
    >(clientsApiPath("validate-gstin"), {
      method: "POST",
      body: JSON.stringify({ gstin }),
      token,
    }),

  /** Verify a GSTIN against Sandbox.co.in Public GST API. */
  gstinVerify: (token: string, gstin: string) =>
    apiFetch<{
      valid: boolean;
      status: string;
      legal_name: string | null;
      trade_name: string | null;
      taxpayer_type: string | null;
      registration_date: string | null;
      raw_response: Record<string, unknown>;
    }>("/api/gstin/verify", {
      method: "POST",
      body: JSON.stringify({ gstin }),
      token,
    }),

  update: (
    token: string,
    id: string,
    data: Database["public"]["Tables"]["client_gstins"]["Update"]
  ) =>
    apiFetch<ClientGstin>(clientsApiPath(id), {
      method: "PATCH",
      body: JSON.stringify(data),
      token,
    }),

  assign: (token: string, id: string, assigned_to: string) =>
    apiFetch<ClientGstin>(clientsApiPath(id, "assign"), {
      method: "PATCH",
      body: JSON.stringify({ assigned_to }),
      token,
    }),

  delete: (token: string, id: string) =>
    apiFetch<void>(clientsApiPath(id), { method: "DELETE", token }),
};


// ─── Reconciliation runs ─────────────────────────────────────────────────────

export const reconciliationsApi = {
  list: (token: string, page = 1, pageSize = 20) =>
    apiFetch<PaginatedResponse<ReconciliationRun>>(
      `/api/reconciliations?page=${page}&page_size=${pageSize}`,
      { token }
    ),

  get: (token: string, id: string) =>
    apiFetch<ReconciliationRun>(`/api/reconciliations/${id}`, { token }),

  getSummary: (token: string, id: string) =>
    apiFetch<ReconciliationSummary>(`/api/reconciliations/${id}/summary`, {
      token,
    }),

  upload: (token: string, formData: FormData) =>
    apiFetch<UploadRunResponse>("/api/reconciliations/upload", {
      method: "POST",
      headers: { Authorization: `Bearer ${token}` },
      body: formData,
    }),

  updateStatus: (
    token: string,
    id: string,
    status: ReconciliationStatus
  ) =>
    apiFetch<ReconciliationRun>(`/api/reconciliations/${id}/status`, {
      method: "PATCH",
      body: JSON.stringify({ status }),
      token,
    }),

  finalize: (token: string, id: string) =>
    apiFetch<ReconciliationRun>(`/api/reconciliations/${id}/finalize`, {
      method: "POST",
      token,
    }),
};

/** Row from GET `/api/reconcile/runs` (FastAPI reconcile router). */
export interface ReconcileRunListRow {
  id: string;
  client_gstin_id: string;
  period: string;
  status: string;
  progress_percent?: number | null;
  status_message?: string | null;
  gstr_records_imported?: number | null;
  pr_records_imported?: number | null;
  matched_count?: number | null;
  unmatched_count?: number | null;
  itc_at_risk?: number | null;
  wrongful_itc?: number | null;
  late_itc?: number | null;
  created_at: string;
  updated_at?: string | null;
  processing_started_at?: string | null;
  completed_at?: string | null;
  run_summary?: Record<string, unknown> | null;
  is_locked?: boolean | null;
  finalized_at?: string | null;
  finalized_by?: string | null;
  finalized_by_name?: string | null;
  trade_name?: string | null;
  client_gstin?: string | null;
}

export const reconcileRunsApi = {
  list: (
    token: string,
    params?: {
      status?: string;
      limit?: number;
      client_gstin_id?: string;
    }
  ) => {
    const sp = new URLSearchParams();
    if (params?.status) sp.set("status", params.status);
    if (params?.limit != null) sp.set("limit", String(params.limit));
    if (params?.client_gstin_id)
      sp.set("client_gstin_id", params.client_gstin_id);
    const q = sp.toString();
    return apiFetch<ReconcileRunListRow[]>(
      `/api/reconcile/runs${q ? `?${q}` : ""}`,
      { token }
    );
  },

  retryFailed: (token: string, runId: string) =>
    apiFetch<{ run_id: string; status: string }>(
      `/api/reconcile/runs/${encodeURIComponent(runId)}/retry`,
      { method: "POST", token }
    ),

  finalizeRun: (token: string, runId: string) =>
    apiFetch<unknown>(
      `/api/reconcile/runs/${encodeURIComponent(runId)}/finalize`,
      {
        method: "POST",
        token,
        body: JSON.stringify({ checklist_snapshot: {} }),
      }
    ),

  /** GET `/api/reconcile/runs/{id}/summary` — same shape as results page `RunSummary`. */
  runSummary: (token: string, runId: string) =>
    apiFetch<ReconcileRunSummaryDto>(
      `/api/reconcile/runs/${encodeURIComponent(runId)}/summary`,
      { token }
    ),

  logSupplierFollowupAudit: (
    token: string,
    runId: string,
    body: import("@/lib/supplierFollowupLetter").FollowupAuditPayload
  ) =>
    apiFetch<{ id: string; status: string; generated_at: string }>(
      `/api/reconcile/runs/${encodeURIComponent(runId)}/supplier-followup/audit`,
      { method: "POST", token, body: JSON.stringify(body) }
    ),
};

export type { SupplierFollowupAuditRow } from "@/lib/followupAudit";

export const followupAuditApi = {
  listForRun: (token: string, runId: string, query = "") =>
    apiFetch<import("@/lib/followupAudit").SupplierFollowupAuditRow[]>(
      `/api/reconcile/runs/${encodeURIComponent(runId)}/supplier-followup/audit${query}`,
      { token }
    ),

  listForClient: (token: string, clientGstinId: string, query = "") =>
    apiFetch<import("@/lib/followupAudit").SupplierFollowupAuditRow[]>(
      `/api/reconcile/clients/${encodeURIComponent(clientGstinId)}/supplier-followup/audit${query}`,
      { token }
    ),
};

// ─── GSTR-3B Reconciliation ───────────────────────────────────────────────────

export type Gstr3bHeadResult = {
  gstr2b: number;
  gstr3b: number;
  difference: number;
  status: "MATCHED" | "OVERCLAIMED" | "UNDERCLAIMED";
};

export type Gstr3bOutwardSupply = {
  taxable_value: number;
  igst: number;
  total: number;
};

export type Gstr3bReconciliationResult = {
  id: string;
  run_id: string;
  client_gstin: string;
  tax_period: string;
  overall_status: "MATCHED" | "OVERCLAIMED" | "UNDERCLAIMED";
  igst: Gstr3bHeadResult;
  cgst: Gstr3bHeadResult;
  sgst: Gstr3bHeadResult;
  total: Gstr3bHeadResult;
  outward_supply: Gstr3bOutwardSupply;
  uploaded_at: string;
};

export const gstr3bApi = {
  upload: (token: string, runId: string, file: File): Promise<Gstr3bReconciliationResult> => {
    const form = new FormData();
    form.append("file", file);
    return apiFetch<Gstr3bReconciliationResult>(
      `/api/reconcile/runs/${encodeURIComponent(runId)}/gstr3b`,
      { method: "POST", body: form, token }
    );
  },

  get: (token: string, runId: string): Promise<Gstr3bReconciliationResult> =>
    apiFetch<Gstr3bReconciliationResult>(
      `/api/reconcile/runs/${encodeURIComponent(runId)}/gstr3b`,
      { token }
    ),
};

/** Subset of reconciliation run summary for celebrate / widgets. */
export interface ReconcileRunSummaryDto {
  run_id: string;
  matched_count: number;
  missed_itc_count: number;
  wrongful_risk_count: number;
  missed_itc_total_amount?: number;
  wrongful_risk_total_amount?: number;
  wrongful_risk_purchase_total_amount?: number;
  status?: string;
}

// ─── Records ──────────────────────────────────────────────────────────────────

export const recordsApi = {
  listGstr: (token: string, runId: string, page = 1, pageSize = 100) =>
    apiFetch<PaginatedResponse<GstrRecord>>(
      `/api/reconciliations/${runId}/gstr?page=${page}&page_size=${pageSize}`,
      { token }
    ),

  listPr: (token: string, runId: string, page = 1, pageSize = 100) =>
    apiFetch<PaginatedResponse<PrRecord>>(
      `/api/reconciliations/${runId}/pr?page=${page}&page_size=${pageSize}`,
      { token }
    ),
};

// ─── Mismatch notes ───────────────────────────────────────────────────────────

export const notesApi = {
  list: (token: string, runId: string) =>
    apiFetch<MismatchNote[]>(`/api/reconciliations/${runId}/notes`, { token }),

  create: (
    token: string,
    data: Database["public"]["Tables"]["mismatch_notes"]["Insert"]
  ) =>
    apiFetch<MismatchNote>("/api/notes", {
      method: "POST",
      body: JSON.stringify(data),
      token,
    }),
};

// ─── Team & auth ─────────────────────────────────────────────────────────────

/**
 * Prefix for `auth.router` in FastAPI (`app/routers/auth.py`).
 * Mounted in `app/main.py`: `include_router(auth.router, prefix="/api/v1/auth")`.
 */
const AUTH_ROUTER_PREFIX = "/api/v1/auth";

export const authApi = {
  /** GET `/me` on the main auth router → `/api/v1/auth/me`. */
  me: (token: string, options?: { fresh?: boolean }) => {
    const suffix = options?.fresh ? `?_=${Date.now()}` : "";
    return apiFetch<AuthMeProfile>(`${AUTH_ROUTER_PREFIX}/me${suffix}`, {
      token,
      cache: "no-store",
      headers: {
        "Cache-Control": "no-cache",
        Pragma: "no-cache",
      },
    });
  },
};

export const auditLogsApi = {
  list: (
    token: string,
    params: {
      firm_id?: string;
      user_id?: string;
      action?: string;
      from_date?: string;
      to_date?: string;
      limit?: number;
      offset?: number;
    } = {}
  ) => {
    const qs = new URLSearchParams();
    if (params.firm_id) qs.set("firm_id", params.firm_id);
    if (params.user_id) qs.set("user_id", params.user_id);
    if (params.action) qs.set("action", params.action);
    if (params.from_date) qs.set("from_date", params.from_date);
    if (params.to_date) qs.set("to_date", params.to_date);
    if (params.limit != null) qs.set("limit", String(params.limit));
    if (params.offset != null) qs.set("offset", String(params.offset));
    const query = qs.toString();
    return apiFetch<import("@/lib/activityLog").AuditLogListResponse>(
      `/api/audit-logs${query ? `?${query}` : ""}`,
      { token }
    );
  },
};

export const teamApi = {
  list: (token: string) =>
    apiFetch<TeamMemberListItem[]>("/api/team/members", { token }),

  invite: (token: string, email: string, role: "admin" | "staff") =>
    apiFetch<{ invited: boolean }>("/api/team/invite", {
      method: "POST",
      body: JSON.stringify({ email, role }),
      token,
    }),

  remove: (token: string, memberId: string) =>
    apiFetch<{ removed: boolean }>(`/api/team/members/${memberId}`, {
      method: "DELETE",
      token,
    }),
};

export interface CreditBatchRow {
  plan: string | null;
  runs_purchased: number | null;
  runs_remaining: number | null;
  expires_at: string | null;
  purchased_at: string | null;
  status: string;
}

export interface BillingStatus {
  plan: string;
  free_runs_remaining: number;
  runs_balance: number;
  credit_batches: CreditBatchRow[];
  expiring_soon: CreditBatchRow[];
  total_spent_paise: number;
  suggested_upgrade: boolean;
}

export interface PaymentHistoryRow {
  payment_id: string;
  created_at: string | null;
  trade_name: string | null;
  period: string | null;
  plan: string | null;
  runs_purchased: number | null;
  base_amount_paise: number | null;
  gst_paise: number | null;
  total_amount_paise: number | null;
  status: string;
  razorpay_payment_id: string | null;
}

export const billingApi = {
  status: (token: string) =>
    apiFetch<BillingStatus>("/api/billing/status", { token }),

  history: (token: string) =>
    apiFetch<PaymentHistoryRow[]>("/api/payments/history", { token }),
};

/** Opens PDF in a new tab (Bearer token). */
export async function openPaymentReceipt(
  token: string,
  paymentId: string
): Promise<void> {
  const res = await fetch(
    `${API_URL}/api/payments/receipt/${encodeURIComponent(paymentId)}`,
    { headers: { Authorization: `Bearer ${token}` } }
  );
  if (!res.ok) {
    throw { detail: `Receipt HTTP ${res.status}`, status: res.status } satisfies ApiError;
  }
  const blob = await res.blob();
  const url = URL.createObjectURL(blob);
  window.open(url, "_blank", "noopener,noreferrer");
  window.setTimeout(() => URL.revokeObjectURL(url), 60_000);
}

export const usersApi = {
  onboardingComplete: (token: string) =>
    apiFetch<{ success: boolean }>("/api/users/onboarding-complete", {
      method: "PATCH",
      body: JSON.stringify({}),
      token,
    }),

  updateProfile: (token: string, data: ProfileUpdatePayload) =>
    apiFetch<AuthMeProfile>("/api/users/profile", {
      method: "PATCH",
      body: JSON.stringify(data),
      token,
    }),
};

// ─── Health ───────────────────────────────────────────────────────────────────

export const healthApi = {
  ping: () => apiFetch<{ status: string }>("/health"),
};

// ─── Import wizard (GSTR-2B + PR) ─────────────────────────────────────────────

export type ImportRunStatus =
  | "draft"
  | "gstr_uploaded"
  | "pr_uploaded"
  | "pending"
  | "processing"
  | "complete"
  | "error"
  | "cancelled";

export interface ImportWizardRun {
  id: string;
  client_id: string;
  firm_owner_id: string | null;
  period: string;
  status: ImportRunStatus;
  current_step: number;
  gstr2b_r2_key: string | null;
  gstr2b_file_name: string | null;
  gstr2b_file_size: number | null;
  gstr2b_file_hash: string | null;
  gstr2b_uploaded_at: string | null;
  gstr2b_record_count: number | null;
  sanity_check_results: SanityCheckItem[] | null;
  pr_r2_key: string | null;
  pr_file_name: string | null;
  pr_file_size: number | null;
  pr_file_hash: string | null;
  pr_uploaded_at: string | null;
  pr_record_count: number | null;
  pr_column_headers: string[] | null;
  column_mapping: ColumnMappingRow[] | null;
  created_by: string;
  created_at: string;
  updated_at: string;
  progress_pct: number;
  status_message: string | null;
  error_detail: string | null;
}

export interface SanityCheckItem {
  id: string;
  label: string;
  status: "pass" | "warning" | "error";
  detail: string;
  affected_records: { gstin: string; invoice_number: string }[];
  acknowledged?: boolean;
}

export interface ColumnMappingRow {
  standard_field: string;
  detected_column: string | null;
  confidence: "high" | "medium" | "low" | "not_found";
  sample_values: string[];
  confirmed: boolean;
}

export interface SignedUploadResponse {
  upload_url: string;
  key: string;
  method: string;
  headers: Record<string, string>;
}

export interface DetectColumnsResponse {
  columns: ColumnMappingRow[];
  all_headers: string[];
}

export interface RunPollStatus {
  status: string;
  progress_pct: number;
  message: string;
}

export const importWizardApi = {
  createRun: (token: string, body: { client_id: string; period: string }) => {
    const t = token.trim();
    return apiFetch<ImportWizardRun>("/api/runs", {
      method: "POST",
      body: JSON.stringify(body),
      token: t,
      headers: { Authorization: `Bearer ${t}` },
    });
  },

  getRun: (token: string, runId: string) =>
    apiFetch<ImportWizardRun>(`/api/runs/${runId}`, { token }),

  patchRun: (
    token: string,
    runId: string,
    body: {
      current_step?: number;
      column_mapping?: ColumnMappingRow[];
      sanity_check_results?: SanityCheckItem[];
    }
  ) =>
    apiFetch<ImportWizardRun>(`/api/runs/${runId}`, {
      method: "PATCH",
      body: JSON.stringify(body),
      token,
    }),

  signedUrl: (
    token: string,
    q: { type: "gstr2b" | "purchase_register"; run_id: string; file_name?: string; content_type?: string }
  ) => {
    const p = new URLSearchParams({
      type: q.type,
      run_id: q.run_id,
    });
    if (q.file_name) p.set("file_name", q.file_name);
    if (q.content_type) p.set("content_type", q.content_type);
    return apiFetch<SignedUploadResponse>(`/api/uploads/signed-url?${p}`, { token });
  },

  gstr2bUploadComplete: (
    token: string,
    runId: string,
    body: { r2_key: string; file_name: string; file_size: number; file_hash: string }
  ) =>
    apiFetch<ImportWizardRun>(`/api/runs/${runId}/uploads/gstr2b/complete`, {
      method: "POST",
      body: JSON.stringify(body),
      token,
    }),

  prUploadComplete: (
    token: string,
    runId: string,
    body: { r2_key: string; file_name: string; file_size: number; file_hash: string }
  ) =>
    apiFetch<ImportWizardRun>(`/api/runs/${runId}/uploads/purchase-register/complete`, {
      method: "POST",
      body: JSON.stringify(body),
      token,
    }),

  sanityCheckGstr2b: (token: string, runId: string) =>
    apiFetch<{ checks: SanityCheckItem[] }>(`/api/runs/${runId}/sanity-check/gstr2b`, {
      method: "POST",
      token,
    }),

  acknowledgeWarning: (
    token: string,
    runId: string,
    body: { check_id: string; check_label: string }
  ) =>
    apiFetch<{ ok: boolean }>(`/api/runs/${runId}/warnings/acknowledge`, {
      method: "POST",
      body: JSON.stringify(body),
      token,
    }),

  confirmMapping: (
    token: string,
    runId: string,
    body: {
      field: string;
      detected_column: string | null;
      confidence: string;
      method: "manual" | "auto";
    }
  ) =>
    apiFetch<{ ok: boolean }>(`/api/runs/${runId}/mapping/confirm`, {
      method: "POST",
      body: JSON.stringify(body),
      token,
    }),

  detectColumns: (token: string, runId: string) =>
    apiFetch<DetectColumnsResponse>(`/api/runs/${runId}/detect-columns`, {
      method: "POST",
      token,
    }),

  start: (token: string, runId: string) =>
    apiFetch<ImportWizardRun>(`/api/runs/${runId}/start`, {
      method: "POST",
      body: JSON.stringify({}),
      token,
    }),

  cancel: (token: string, runId: string) =>
    apiFetch<ImportWizardRun>(`/api/runs/${runId}/cancel`, {
      method: "POST",
      token,
    }),

  /** Short poll: one fast GET to Railway — never via Next.js proxy (avoids 300s Vercel timeout). */
  pollStatus: (token: string, runId: string) =>
    apiFetch<RunPollStatus>(`/api/runs/${runId}/status`, {
      token,
      directBackend: true,
      timeoutMs: STATUS_POLL_REQUEST_TIMEOUT_MS,
    }),

  retry: (token: string, runId: string) =>
    apiFetch<ImportWizardRun>(`/api/runs/${runId}/retry`, {
      method: "POST",
      token,
    }),
};

export interface NotificationPreferences {
  run_completed: boolean;
  runs_expiring_soon: boolean;
  payment_receipts: boolean;
}

export const notificationsApi = {
  getPreferences: (token: string) =>
    apiFetch<NotificationPreferences>("/api/v1/notifications/preferences", { token }),

  updatePreferences: (token: string, preferences: NotificationPreferences) =>
    apiFetch<NotificationPreferences>("/api/v1/notifications/preferences", {
      method: "PUT",
      body: JSON.stringify(preferences),
      token,
    }),
};

// ─── Manage Data (admin raw file storage) ─────────────────────────────────────

export interface ManageDataFileInfo {
  name: string | null;
  size: number | null;
  uploaded_at: string | null;
  deleted_at: string | null;
  is_deleted: boolean;
}

export interface ManageDataRow {
  run_id: string;
  client_gstin_id: string;
  client_name: string;
  gstin: string;
  period: string | null;
  status: string;
  created_at: string | null;
  gstr2b: ManageDataFileInfo;
  pr: ManageDataFileInfo;
}

export type ManageDataFileType = "gstr2b" | "pr";

export const manageDataApi = {
  list: (token: string) =>
    apiFetch<ManageDataRow[]>("/api/v1/manage-data", { token }),

  deleteFile: (token: string, runId: string, fileType: ManageDataFileType) =>
    apiFetch<{ ok: boolean; run_id: string; file_type: ManageDataFileType }>(
      `/api/v1/manage-data/${encodeURIComponent(runId)}/${fileType}`,
      { method: "DELETE", token }
    ),

  downloadUrl: (token: string, runId: string, fileType: ManageDataFileType) =>
    apiFetch<{ download_url: string }>(
      `/api/v1/manage-data/${encodeURIComponent(runId)}/${fileType}/download`,
      { token }
    ),
};

