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
  Database["public"]["Tables"]["client_gstins"]["Row"] & {
    gstn_access_token?: string | null;
    gstn_token_expiry?: string | null;
  };
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
  gstin_limit?: number | null;
  subscription_ends_at?: string | null;
  firm_city?: string | null;
  icai_membership_number?: string | null;
  firm_gstin?: string | null;
  onboarding_completed?: boolean | null;
  auto_approve_confidence_threshold?: number | null;
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
  /** Original FastAPI ``detail`` (object or string) when the body was JSON. */
  rawDetail?: unknown;
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
  if (typeof raw === "object") {
    const obj = raw as Record<string, unknown>;
    const errorKey =
      typeof obj.error === "string" && obj.error.trim() ? obj.error.trim() : "";
    if (typeof obj.message === "string" && obj.message.trim()) {
      return errorKey ? `${errorKey}: ${obj.message}` : obj.message;
    }
    if (Array.isArray(obj.errors) && obj.errors.length > 0) {
      const errs = obj.errors
        .map((item) =>
          typeof item === "string"
            ? item
            : typeof item === "object" && item && "msg" in item
              ? String((item as { msg: unknown }).msg)
              : JSON.stringify(item)
        )
        .join("; ");
      return errorKey ? `${errorKey}: ${errs}` : errs;
    }
    try {
      return JSON.stringify(raw);
    } catch {
      return fallback;
    }
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

/** Browser paths that have a Next.js same-origin proxy (avoids CORS / Failed to fetch). */
function usesSameOriginProxy(path: string): boolean {
  return (
    path.startsWith("/api/reconcile") ||
    path.startsWith("/api/notes") ||
    path.startsWith("/api/audit-observations") ||
    path.startsWith("/api/reconciliation") ||
    path.startsWith("/api/einvoice-recon")
  );
}

/** Resolve fetch URL — browser reconcile/notes/etc. go through same-origin Next.js proxy. */
function resolveApiUrl(path: string, directBackend = false): string {
  const normalized = normalizeApiPath(path);
  if (directBackend) {
    return backendApiUrl(normalized);
  }
  if (typeof window !== "undefined" && usesSameOriginProxy(normalized)) {
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
    let rawDetail: unknown;
    try {
      const json = (await res.json()) as { detail?: unknown };
      rawDetail = json.detail;
      detail = formatApiErrorDetail(json.detail, detail);
    } catch {
      // Response body was not JSON
    }
    throw { detail, status: res.status, rawDetail } satisfies ApiError;
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

// ─── GSTN taxpayer OTP (Sandbox GSP) ─────────────────────────────────────────
// Backend routes: POST /api/clients/{client_gstin_id}/gstn/send-otp|verify-otp

/** Parsed GSTR-2B from POST .../gstn/fetch, plus GSTN JSON for wizard upload. */
export type GstnFetchGstr2bResult = {
  schema_version?: string;
  buyer_gstin?: string;
  period?: string;
  records?: unknown[];
  skipped?: unknown[];
  total_parsed: number;
  total_skipped?: number;
  /** GSTN-shaped ``{ data: { gstin, rtnprd, b2b, ... } }`` for R2 upload. */
  upload_payload: Record<string, unknown>;
  [key: string]: unknown;
};

/** IMS overlay summary from POST .../gstn/fetch-ims. */
export type GstnFetchImsResult = {
  gstin: string;
  year: number;
  month: number;
  counts: Record<string, Record<string, number>>;
  total_by_status: Record<string, number>;
  status_counts: Record<string, number>;
  invoices_fetched: number;
  status_map_size: number;
  pending_action_count: number;
};

export const gstnApi = {
  sendOtp: (
    token: string,
    client_gstin_id: string,
    body: { gstin: string; username: string }
  ) =>
    apiFetch<{ message: string; txn?: string }>(
      clientsApiPath(client_gstin_id, "gstn", "send-otp"),
      {
        method: "POST",
        body: JSON.stringify(body),
        token,
      }
    ),

  verifyOtp: (
    token: string,
    client_gstin_id: string,
    body: { gstin: string; username: string; otp: string }
  ) =>
    apiFetch<{ message: string }>(
      clientsApiPath(client_gstin_id, "gstn", "verify-otp"),
      {
        method: "POST",
        body: JSON.stringify(body),
        token,
      }
    ),

  fetchGstr2b: (
    token: string,
    client_gstin_id: string,
    body: { year: string; month: string }
  ) =>
    apiFetch<GstnFetchGstr2bResult>(
      clientsApiPath(client_gstin_id, "gstn", "fetch"),
      {
        method: "POST",
        body: JSON.stringify(body),
        token,
      }
    ),

  fetchIms: (
    token: string,
    client_gstin_id: string,
    body: { year: string; month: string }
  ) =>
    apiFetch<GstnFetchImsResult>(
      clientsApiPath(client_gstin_id, "gstn", "fetch-ims"),
      {
        method: "POST",
        body: JSON.stringify(body),
        token,
      }
    ),
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
  /** Computed label from the API (not a DB column). Currently always "GSTR-2B". */
  display_type?: string | null;
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
      /** Skip expensive matched_itc payload backfill on the server. */
      light?: boolean;
    }
  ) => {
    const sp = new URLSearchParams();
    if (params?.status) sp.set("status", params.status);
    if (params?.limit != null) sp.set("limit", String(params.limit));
    if (params?.client_gstin_id)
      sp.set("client_gstin_id", params.client_gstin_id);
    if (params?.light) sp.set("light", "true");
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
  cgst?: number;
  sgst?: number;
  cess?: number;
};

/** Additive Rule 88D / DRC-01C check (does not change overall_status). */
export type Gstr3bDrc01cResult = {
  threshold_status: "CLEAR" | "BELOW_THRESHOLD" | "DRC01C_TRIGGER" | string;
  excess_amount: number;
  excess_pct: number | null;
  pct_threshold: number;
  amount_threshold: number;
  triggers_drc01c: boolean;
};

export type Gstr3bTaxHeads = {
  igst: number;
  cgst: number;
  sgst: number;
  cess: number;
};

export type Gstr3bSupplyRow = {
  taxable_value: number;
  igst: number;
  cgst: number;
  sgst: number;
  cess: number;
};

export type Gstr3bInwardSupRow = {
  ty: string;
  inter: number;
  intra: number;
};

/** Full filed GSTR-3B as parsed (additive; may be null if raw unparseable). */
export type Gstr3bFiledSummary = {
  outward_supply: Gstr3bOutwardSupply;
  osup_zero: Gstr3bSupplyRow;
  osup_nil_exmp: Gstr3bSupplyRow;
  isup_rev: Gstr3bSupplyRow;
  osup_nongst: Gstr3bSupplyRow;
  itc_avl: Gstr3bTaxHeads;
  itc_rev: Gstr3bTaxHeads;
  itc_net: Gstr3bTaxHeads;
  itc_inelg: Gstr3bTaxHeads;
  itc_avl_by_source: Record<string, Gstr3bTaxHeads>;
  inward_sup: Gstr3bInwardSupRow[];
  interest_late_fee: Gstr3bTaxHeads;
  late_fee: Gstr3bTaxHeads;
};

export type Gstr3bReconciliationResult = {
  id: string;
  run_id: string;
  client_gstin: string;
  tax_period: string;
  overall_status: "MATCHED" | "OVERCLAIMED" | "UNDERCLAIMED" | "MIXED";
  igst: Gstr3bHeadResult;
  cgst: Gstr3bHeadResult;
  sgst: Gstr3bHeadResult;
  total: Gstr3bHeadResult;
  outward_supply: Gstr3bOutwardSupply;
  uploaded_at: string;
  drc01c?: Gstr3bDrc01cResult | null;
  filed?: Gstr3bFiledSummary | null;
  client_gstin_id?: string | null;
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

// ─── GSTR-9C ITC FY rollup (practical internal view) ──────────────────────────

export type Gstr9cItcMonthStatus = "both" | "run_only" | "missing";

export type Gstr9cItcMonthRow = {
  period: string;
  month_label: string;
  status: Gstr9cItcMonthStatus;
  run_id: string | null;
  run_status: string | null;
  matched_itc_paise: number | null;
  matched_itc_rupees: number | null;
  claimed_itc_rupees: number | null;
  claimed_igst_rupees: number | null;
  claimed_cgst_rupees: number | null;
  claimed_sgst_rupees: number | null;
  variance_rupees: number | null;
  included_in_variance: boolean;
  missed_itc_paise: number | null;
  itc_at_risk_paise: number | null;
  wrongful_itc_paise: number | null;
};

export type Gstr9cItcFyTotals = {
  matched_itc_paise: number;
  matched_itc_rupees: number;
  claimed_itc_rupees: number;
  variance_matched_itc_rupees: number;
  variance_claimed_itc_rupees: number;
  variance_rupees: number | null;
  months_in_variance: number;
  partial_label: string;
};

export type Gstr9cItcFyRollup = {
  client_gstin_id: string;
  gstin: string;
  trade_name: string | null;
  fy: string;
  disclaimer: string;
  is_complete: boolean;
  variance_available: boolean;
  months_with_both: number;
  months_with_run: number;
  months_run_only: number;
  months_missing: number;
  months: Gstr9cItcMonthRow[];
  totals: Gstr9cItcFyTotals;
};

export const gstr9cItcApi = {
  fyRollup: (token: string, clientGstinId: string, fy?: string) => {
    const sp = new URLSearchParams();
    if (fy) sp.set("fy", fy);
    const q = sp.toString();
    return apiFetch<Gstr9cItcFyRollup>(
      `/api/reconcile/clients/${encodeURIComponent(clientGstinId)}/gstr9c-itc-fy${
        q ? `?${q}` : ""
      }`,
      {
        token,
        cache: "no-store",
        headers: {
          "Cache-Control": "no-cache",
          Pragma: "no-cache",
        },
      }
    );
  },
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
  status_message?: string | null;
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

/** Lightweight dashboard Quick Stats + Needs Attention (no payload backfill). */
export type DashboardAttentionItem = {
  client_id: string;
  trade_name: string;
  gstin: string;
  run_id: string | null;
  /** UI status: PENDING | IMPORTING | MATCHING | COMPLETE | FINALIZED | FAILED */
  status: string | null;
  period: string | null;
  missed_itc: number | null;
  compliance_risk: string | null;
  priority_score: number;
};

export type DashboardSummary = {
  total_clients: number;
  pending_this_month: number;
  ready_for_review: number;
  failed_client_count: number;
  show_all_finalized_banner: boolean;
  total_itc_protected: number;
  itc_protected_has_data: boolean;
  itc_at_risk: number;
  team_members: number;
  attention: DashboardAttentionItem[];
};

export const dashboardApi = {
  summary: (token: string) =>
    apiFetch<DashboardSummary>("/api/dashboard/summary", { token }),
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
  gstin_limit?: number;
  gstins_used?: number;
  subscription_ends_at?: string | null;
  subscription_active?: boolean;
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

// ─── Vendor compliance scorecard ─────────────────────────────────────────────

export type VendorScorecardSort =
  | "risk_score"
  | "clients_touched_count"
  | "mismatch_rate"
  | "rule37_open_count"
  | "late_filing_rate"
  | "supplier_gstin_normalized"
  | "total_invoices"
  | "last_updated_at";

export interface VendorScorecardRow {
  supplier_gstin: string;
  supplier_trade_name: string;
  clients_touched_count: number;
  client_gstin_ids: string[];
  total_invoices: number;
  mismatch_invoice_count: number;
  mismatch_rate: number;
  rule37_open_count: number;
  rule37_at_risk_paise: number;
  section_17_5_count: number;
  late_filing_count: number;
  late_filing_rate: number;
  pr_only_count: number;
  quarterly_filer_flag: boolean;
  risk_score: number;
  last_updated_at: string | null;
}

export interface VendorScorecardListResponse {
  items: VendorScorecardRow[];
  total: number;
  limit: number;
  offset: number;
  signal_notes: Record<string, string>;
}

export interface VendorScorecardClientTouch {
  client_gstin_id: string;
  gstin: string;
  trade_name: string;
}

export interface VendorScorecardDetailResponse {
  supplier: VendorScorecardRow;
  clients: VendorScorecardClientTouch[];
  signal_notes: Record<string, string>;
}

export const vendorsApi = {
  scorecard: (
    token: string,
    params?: {
      limit?: number;
      offset?: number;
      sort?: VendorScorecardSort;
      order?: "asc" | "desc";
      q?: string;
    }
  ) => {
    const sp = new URLSearchParams();
    if (params?.limit != null) sp.set("limit", String(params.limit));
    if (params?.offset != null) sp.set("offset", String(params.offset));
    if (params?.sort) sp.set("sort", params.sort);
    if (params?.order) sp.set("order", params.order);
    if (params?.q?.trim()) sp.set("q", params.q.trim());
    const qs = sp.toString();
    return apiFetch<VendorScorecardListResponse>(
      `/api/vendors/scorecard${qs ? `?${qs}` : ""}`,
      { token }
    );
  },

  scorecardDetail: (token: string, supplierGstin: string) =>
    apiFetch<VendorScorecardDetailResponse>(
      `/api/vendors/scorecard/${encodeURIComponent(supplierGstin)}`,
      { token }
    ),
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
  /** Optional GSTR-3B period when ITC for this PR batch was claimed (YYYY-MM-01). */
  itc_claimed_period: string | null;
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
  /** When true, Continue/Start stay disabled until the user acknowledges. */
  requires_acknowledgment?: boolean;
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
  saved_mapping?: ClientImportMappingRow[] | null;
  saved_mapping_covers?: boolean;
  schema_ok?: boolean;
  pr_record_count?: number;
  /** Visible when PR rows lack invoice_number after per-sheet mapping. */
  pr_parse_warning?: string | null;
  missing_invoice_number_count?: number;
  /** Present when 2+ Excel sheets were auto-combined (must be acknowledged). */
  multi_sheet_combine?: SanityCheckItem | null;
  /** Present when PR rows lack invoice_number (must be acknowledged). */
  missing_invoice_number?: SanityCheckItem | null;
  sanity_check_results?: SanityCheckItem[] | null;
}

export type ImportTargetField =
  | "gstin"
  | "invoice_number"
  | "invoice_date"
  | "taxable_value"
  | "cgst"
  | "sgst"
  | "igst"
  | "cess";

export interface ClientImportMappingRow {
  id?: string;
  client_gstin_id?: string;
  source_column_name: string;
  target_field: ImportTargetField;
  created_at?: string;
  updated_at?: string;
}

export interface ClientImportMappingItem {
  source_column_name: string;
  target_field: ImportTargetField;
}

export interface RegisterValidationIssue {
  severity: "error" | "warning" | "info";
  code: string;
  message: string;
}

export interface RegisterTypeDetection {
  register_type: "purchase" | "sales" | "ambiguous";
  confidence: "high" | "medium" | "low";
  is_tally_export: boolean;
  source_software: string;
  purchase_score?: number;
  sales_score?: number;
  reasons: string[];
  suggested_pipeline: "gstr2b" | "gstr1" | null;
  requires_manual_choice: boolean;
  headers?: string[];
  sheet_names?: string[];
  help_copy?: string | null;
  validation_issues: RegisterValidationIssue[];
  effective_type?: "purchase" | "sales" | null;
  override_applied?: boolean;
  pipeline_mismatch?: boolean;
  context_help_copy?: string | null;
}

export interface PrDetectColumnsResponse {
  headers: string[];
  schema_ok: boolean;
  saved_mapping: ClientImportMappingRow[] | null;
  saved_mapping_covers: boolean;
  register_type_detection?: RegisterTypeDetection | null;
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
      /** YYYY-MM / YYYY-MM-01; empty string clears. */
      itc_claimed_period?: string;
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
    body: {
      r2_key: string;
      file_name: string;
      file_size: number;
      file_hash: string;
      itc_claimed_period?: string | null;
    }
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

export const prUploadApi = {
  detectColumns: async (
    token: string,
    file: File,
    clientGstinId?: string
  ): Promise<PrDetectColumnsResponse> => {
    const fd = new FormData();
    fd.append("file", file);
    if (clientGstinId) fd.append("client_gstin_id", clientGstinId);
    return apiFetch<PrDetectColumnsResponse>("/api/pr-upload/detect-columns", {
      method: "POST",
      token,
      body: fd,
    });
  },

  getMapping: (token: string, clientGstinId: string) =>
    apiFetch<{ mappings: ClientImportMappingRow[] | null }>(
      `/api/pr-upload/mapping/${clientGstinId}`,
      { token }
    ),

  saveMapping: (
    token: string,
    clientGstinId: string,
    mappings: ClientImportMappingItem[]
  ) =>
    apiFetch<{ mappings: ClientImportMappingRow[] }>(
      `/api/pr-upload/mapping/${clientGstinId}`,
      {
        method: "POST",
        body: JSON.stringify({ mappings }),
        token,
      }
    ),

  deleteMapping: (token: string, clientGstinId: string) =>
    apiFetch<{ ok: boolean }>(`/api/pr-upload/mapping/${clientGstinId}`, {
      method: "DELETE",
      token,
    }),
};

export const registerUploadApi = {
  detectType: async (
    token: string,
    file: File,
    opts?: {
      expectedType?: "purchase" | "sales";
      overrideType?: "purchase" | "sales";
      clientGstinId?: string;
    }
  ): Promise<RegisterTypeDetection> => {
    const fd = new FormData();
    fd.append("file", file);
    if (opts?.expectedType) fd.append("expected_type", opts.expectedType);
    if (opts?.overrideType) fd.append("override_type", opts.overrideType);
    if (opts?.clientGstinId) fd.append("client_gstin_id", opts.clientGstinId);
    return apiFetch<RegisterTypeDetection>("/api/register-upload/detect-type", {
      method: "POST",
      token,
      body: fd,
    });
  },

  help: (token: string, registerType?: "purchase" | "sales") => {
    const q = registerType ? `?register_type=${registerType}` : "";
    return apiFetch<{
      purchase?: string;
      sales?: string;
      help_copy?: string;
    }>(`/api/register-upload/help${q}`, { token });
  },
};

export interface NotificationPreferences {
  run_completed: boolean;
  runs_expiring_soon: boolean;
  payment_receipts: boolean;
  rule37_alerts: boolean;
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

export const reconcileSettingsApi = {
  updateAutoApproveThreshold: (token: string, threshold: number) =>
    apiFetch<AuthMeProfile>("/api/users/auto-approve-threshold", {
      method: "PATCH",
      body: JSON.stringify({ auto_approve_confidence_threshold: threshold }),
      token,
    }),
};

// ─── Tally Bridge ─────────────────────────────────────────────────────────────

export interface TallyBridgeKeyRow {
  id: string;
  company_name: string;
  last_synced_at: string | null;
  created_at?: string | null;
}

export interface TallyBridgeStatus {
  account_id: string;
  has_key: boolean;
  keys: TallyBridgeKeyRow[];
  last_synced_at: string | null;
}

export interface TallyBridgeCreateKeyResponse {
  id: string;
  api_key: string;
  account_id: string;
  company_name: string;
  created_at: string;
  last_synced_at: string | null;
}

export const tallyBridgeApi = {
  status: (token: string) =>
    apiFetch<TallyBridgeStatus>("/api/tally-sync/status", { token }),

  createKey: (token: string, company_name = "") =>
    apiFetch<TallyBridgeCreateKeyResponse>("/api/tally-sync/keys", {
      method: "POST",
      body: JSON.stringify({ company_name }),
      token,
    }),

  agentDownloadUrl: () => `${API_URL}/api/tally-sync/agent`,
  agentExeDownloadUrl: () => `${API_URL}/api/tally-sync/agent-exe`,
  configExampleDownloadUrl: () =>
    `${API_URL}/api/tally-sync/agent-config-example`,
};

// ─── GSTR-1 filing (Sandbox / GSTN) ───────────────────────────────────────────

export type FilingDecisionNeeded =
  | "inv_typ"
  | "ntty"
  | "exp_typ"
  | "table_classification"
  | string;

export type FilingReadinessVerdict = {
  can_save: boolean;
  can_file: boolean;
  summary: string;
  save_blockers: string[];
  file_blockers: string[];
  advisory: string[];
};

export type FilingPendingReviewItem = {
  suggested_table: string;
  reason: string;
  proposed_inv_typ: string | null;
  decision_needed: FilingDecisionNeeded;
  context: Record<string, unknown>;
};

export type FilingExternalInputGap = {
  table: string;
  filing_period: string;
  reason: string;
  message: string;
  missing_fields: string[];
  blocks_file: boolean;
};

export type FilingReadinessResponse = {
  gstin: string;
  client_gstin_id: string;
  filing_period: string;
  filer_state: string;
  filing_readiness: FilingReadinessVerdict;
  pending_review: FilingPendingReviewItem[];
  pending_review_by_table: Record<string, FilingPendingReviewItem[]>;
  pending_review_count: number;
  external_input_gaps: FilingExternalInputGap[];
  external_input_tables: string[];
  save_section_keys: string[];
  row_accounting: {
    total_rows: number;
    saved: number;
    pending_review: number;
    external_input: number;
    skipped: number;
    by_lane: Record<string, number>;
  };
  record_count?: number;
  source_filename?: string | null;
};

export type FilingSaveResponse = {
  run_id: string;
  reference_id: string;
  status: string;
  filing_readiness: FilingReadinessVerdict;
  pending_review_count: number;
  external_input_tables: string[];
  save_payload_keys: string[];
};

export type FilingStatusResponse = {
  period: string;
  reference_id: string;
  data: unknown;
  gstn_status_cd: string | null;
  outer_status_cd: string | null;
  gstn_success: boolean;
  gstn_failed: boolean;
  run_status: string | null;
  error_cd: string | null;
  error_message: string | null;
};

export type FilingSessionVerifyResponse = {
  session_id: string;
  gstin: string;
  token_expires_at: string | null;
  session_expires_at?: string | null;
  status: string;
};

export type FilingEvcOtpResponse = {
  period: string;
  message: string;
  status_cd?: string | null;
  gstn_status_cd?: string | null;
  outer_status_cd?: string | null;
};

export type FilingFileResponse = {
  period: string;
  status: string;
  ack_number: string | null;
  gstn_status_cd?: string | null;
  outer_status_cd?: string | null;
};

function filingPeriodPath(period: string): string {
  return `/api/filing/gstr-1/${encodeURIComponent(period.trim())}`;
}

export type FilingFeaturesResponse = {
  gstr1_filing_enabled: boolean;
  gstr3b_filing_enabled: boolean;
};

export type FilingBatchItem = {
  id: string;
  batch_id: string;
  client_gstin_id: string;
  gstin: string;
  filing_run_id?: string | null;
  status:
    | "pending"
    | "in_progress"
    | "saved"
    | "proceeded"
    | "needs_review"
    | "evc_pending"
    | "failed"
    | "filed"
    | "skipped";
  error_code?: string | null;
  error_detail?: string | null;
  created_at: string;
  updated_at: string;
  client_gstins?: { trade_name?: string | null; legal_name?: string | null } | null;
};

export type FilingBatch = {
  id: string;
  firm_id: string;
  created_by: string;
  return_type: "gstr-1";
  period: string;
  status:
    | "pending"
    | "in_progress"
    | "completed"
    | "partially_completed"
    | "failed"
    | "cancelled";
  total_count: number;
  saved_count: number;
  evc_pending_count: number;
  filed_count: number;
  failed_count: number;
  needs_review_count: number;
  created_at: string;
  updated_at: string;
  items?: FilingBatchItem[];
};

export const filingApi = {
  features: () =>
    apiFetch<FilingFeaturesResponse>("/api/filing/features", {
      cache: "no-store",
    }),

  readinessUpload: (
    token: string,
    period: string,
    params: { client_gstin_id: string; sales_register_file: File }
  ) => {
    const form = new FormData();
    form.append("client_gstin_id", params.client_gstin_id);
    form.append("sales_register_file", params.sales_register_file);
    return apiFetch<FilingReadinessResponse>(
      `${filingPeriodPath(period)}/readiness-upload`,
      { method: "POST", body: form, token }
    );
  },

  readiness: (
    token: string,
    period: string,
    body: {
      client_gstin_id: string;
      period: string;
      records: Record<string, unknown>[];
    }
  ) =>
    apiFetch<FilingReadinessResponse>(`${filingPeriodPath(period)}/readiness`, {
      method: "POST",
      body: JSON.stringify(body),
      token,
    }),

  saveUpload: (
    token: string,
    period: string,
    params: {
      client_gstin_id: string;
      sales_register_file: File;
      session_id?: string | null;
      gt?: number;
      cur_gt?: number;
    }
  ) => {
    const form = new FormData();
    form.append("client_gstin_id", params.client_gstin_id);
    form.append("sales_register_file", params.sales_register_file);
    if (params.session_id) form.append("session_id", params.session_id);
    if (params.gt != null) form.append("gt", String(params.gt));
    if (params.cur_gt != null) form.append("cur_gt", String(params.cur_gt));
    return apiFetch<FilingSaveResponse>(
      `${filingPeriodPath(period)}/save-upload`,
      { method: "POST", body: form, token }
    );
  },

  status: (
    token: string,
    period: string,
    params: {
      reference_id: string;
      session_id?: string | null;
      run_id?: string | null;
    }
  ) => {
    const sp = new URLSearchParams();
    sp.set("reference_id", params.reference_id);
    if (params.session_id) sp.set("session_id", params.session_id);
    if (params.run_id) sp.set("run_id", params.run_id);
    return apiFetch<FilingStatusResponse>(
      `${filingPeriodPath(period)}/status?${sp.toString()}`,
      {
        token,
        directBackend: true,
        timeoutMs: STATUS_POLL_REQUEST_TIMEOUT_MS,
        cache: "no-store",
      }
    );
  },

  proceed: (
    token: string,
    period: string,
    body: { session_id?: string | null; run_id?: string | null; is_nil?: string }
  ) =>
    apiFetch<{
      period: string;
      reference_id: string;
      status: string;
      gstn_status_cd?: string | null;
      outer_status_cd?: string | null;
      error_cd?: string | null;
      error_message?: string | null;
    }>(`${filingPeriodPath(period)}/proceed`, {
      method: "POST",
      body: JSON.stringify(body),
      token,
    }),

  evcOtp: (
    token: string,
    period: string,
    body: { pan: string; session_id?: string | null; run_id?: string | null }
  ) =>
    apiFetch<FilingEvcOtpResponse>(`${filingPeriodPath(period)}/evc-otp`, {
      method: "POST",
      body: JSON.stringify(body),
      token,
    }),

  file: (
    token: string,
    period: string,
    body: {
      pan: string;
      otp: string;
      session_id?: string | null;
      run_id?: string | null;
    }
  ) =>
    apiFetch<FilingFileResponse>(`${filingPeriodPath(period)}/file`, {
      method: "POST",
      body: JSON.stringify(body),
      token,
    }),

  generateOtp: (
    token: string,
    body: { gstin: string; username: string; client_gstin_id?: string | null }
  ) =>
    apiFetch<{ message: string; transaction_id?: string; status_cd?: string }>(
      "/api/filing/session/otp/generate",
      { method: "POST", body: JSON.stringify(body), token }
    ),

  verifyOtp: (
    token: string,
    body: {
      gstin: string;
      username: string;
      otp: string;
      client_gstin_id?: string | null;
    }
  ) =>
    apiFetch<FilingSessionVerifyResponse>(
      "/api/filing/session/otp/verify",
      { method: "POST", body: JSON.stringify(body), token }
    ),

  createBatch: (
    token: string,
    body: { period: string; client_gstin_ids: string[]; return_type?: string }
  ) =>
    apiFetch<FilingBatch>("/api/filing/batches", {
      method: "POST",
      body: JSON.stringify(body),
      token,
    }),

  listBatches: (token: string) =>
    apiFetch<{ batches: FilingBatch[] }>("/api/filing/batches", {
      token,
      cache: "no-store",
    }),

  getBatch: (token: string, batchId: string) =>
    apiFetch<FilingBatch>(`/api/filing/batches/${encodeURIComponent(batchId)}`, {
      token,
      cache: "no-store",
    }),

  retryBatch: (token: string, batchId: string) =>
    apiFetch<FilingBatch>(`/api/filing/batches/${encodeURIComponent(batchId)}/retry`, {
      method: "POST",
      token,
    }),
};


// ─── GSTR-3B filing (Sandbox / GSTN) ──────────────────────────────────────────

export type Gstr3bPdcashRow = {
  liab_ldg_id: number;
  trans_typ: number;
  ipd: number;
  cpd: number;
  spd: number;
  cspd: number;
  i_intrpd?: number;
  c_intrpd?: number;
  s_intrpd?: number;
  cs_intrpd?: number;
  c_lfeepd?: number;
  s_lfeepd?: number;
  [key: string]: unknown;
};

export type Gstr3bPditc = {
  liab_ldg_id: number;
  trans_typ: number;
  i_pdi: number;
  i_pdc: number;
  i_pds: number;
  c_pdi: number;
  c_pdc: number;
  s_pdi: number;
  s_pds: number;
  cs_pdcs: number;
  [key: string]: unknown;
};

export type Gstr3bOffsetPreviewResponse = {
  period: string;
  gstin: string;
  pdcash: Gstr3bPdcashRow[];
  pditc: Gstr3bPditc;
  details: Record<string, unknown>;
  ledger: Record<string, unknown>;
};

export type Gstr3bOsupDetSuggestionResponse = {
  available: boolean;
  reason?: string;
  source?: string;
  period?: string;
  run_id?: string | null;
  record_count?: number;
  osup_det?: {
    txval: number;
    iamt: number;
    camt: number;
    samt: number;
    csamt: number;
  };
};

export type Gstr3bItcOthSuggestionResponse = {
  available: boolean;
  reason?: string;
  source?: string;
  period?: string;
  run_id?: string | null;
  record_count?: number;
  iamt?: number;
  camt?: number;
  samt?: number;
  csamt?: number;
};

export type Gstr3bSaveResponse = {
  run_id: string;
  reference_id: string | null;
  status: string;
  period: string;
  outer_status_cd?: string | null;
  gstn_status_cd?: string | null;
  message?: string;
};

export type Gstr3bOffsetResponse = {
  period: string;
  run_id: string;
  reference_id: string | null;
  status: string;
  offset_payload: { pdcash: Gstr3bPdcashRow[]; pditc: Gstr3bPditc };
  outer_status_cd?: string | null;
  gstn_status_cd?: string | null;
  gstn_success?: boolean;
  message?: string;
};

export type Gstr3bStatusResponse = FilingStatusResponse & {
  action?: string | null;
};

export type Gstr3bPeriodLockedDetail = {
  code: "GSTR3B_PERIOD_LOCKED";
  action: string;
  message: string;
  gstin: string;
  period: string;
  locking_run: {
    run_id: string | null;
    status: string | null;
    offset_completed_at: string | null;
    reference_id: string | null;
    offset_payload: unknown;
    tx_pmt_snapshot: unknown;
  };
};

export type Gstr3bOffsetStaleDetail = {
  code: "GSTR3B_OFFSET_STALE";
  message: string;
  period: string;
  posted: { pdcash: Gstr3bPdcashRow[]; pditc: Gstr3bPditc };
  current: { pdcash: Gstr3bPdcashRow[]; pditc: Gstr3bPditc };
};

function gstr3bPeriodPath(period: string): string {
  return `/api/filing/gstr-3b/${encodeURIComponent(period.trim())}`;
}

export function parseGstr3bPeriodLocked(
  err: unknown
): Gstr3bPeriodLockedDetail | null {
  if (!isApiError(err) || err.status !== 409) return null;
  const raw = err.rawDetail;
  if (!raw || typeof raw !== "object") return null;
  const obj = raw as Record<string, unknown>;
  if (obj.code !== "GSTR3B_PERIOD_LOCKED") return null;
  const lr =
    obj.locking_run && typeof obj.locking_run === "object"
      ? (obj.locking_run as Record<string, unknown>)
      : {};
  return {
    code: "GSTR3B_PERIOD_LOCKED",
    action: String(obj.action || ""),
    message: String(obj.message || err.detail),
    gstin: String(obj.gstin || ""),
    period: String(obj.period || ""),
    locking_run: {
      run_id: lr.run_id != null ? String(lr.run_id) : null,
      status: lr.status != null ? String(lr.status) : null,
      offset_completed_at:
        lr.offset_completed_at != null ? String(lr.offset_completed_at) : null,
      reference_id:
        lr.reference_id != null ? String(lr.reference_id) : null,
      offset_payload: lr.offset_payload ?? null,
      tx_pmt_snapshot: lr.tx_pmt_snapshot ?? null,
    },
  };
}

export function parseGstr3bOffsetStale(
  err: unknown
): Gstr3bOffsetStaleDetail | null {
  if (!isApiError(err) || err.status !== 409) return null;
  const raw = err.rawDetail;
  if (!raw || typeof raw !== "object") return null;
  const obj = raw as Record<string, unknown>;
  if (obj.code !== "GSTR3B_OFFSET_STALE") return null;
  const posted =
    obj.posted && typeof obj.posted === "object"
      ? (obj.posted as Gstr3bOffsetStaleDetail["posted"])
      : { pdcash: [], pditc: {} as Gstr3bPditc };
  const current =
    obj.current && typeof obj.current === "object"
      ? (obj.current as Gstr3bOffsetStaleDetail["current"])
      : { pdcash: [], pditc: {} as Gstr3bPditc };
  return {
    code: "GSTR3B_OFFSET_STALE",
    message: String(obj.message || err.detail),
    period: String(obj.period || ""),
    posted,
    current,
  };
}

export const gstr3bFilingApi = {
  details: (
    token: string,
    period: string,
    params: { client_gstin_id: string; session_id?: string | null }
  ) => {
    const sp = new URLSearchParams();
    sp.set("client_gstin_id", params.client_gstin_id);
    if (params.session_id) sp.set("session_id", params.session_id);
    return apiFetch<{
      period: string;
      gstin: string;
      details: Record<string, unknown>;
    }>(`${gstr3bPeriodPath(period)}/details?${sp.toString()}`, { token });
  },

  ledgerBalance: (
    token: string,
    period: string,
    params: { client_gstin_id: string; session_id?: string | null }
  ) => {
    const sp = new URLSearchParams();
    sp.set("client_gstin_id", params.client_gstin_id);
    if (params.session_id) sp.set("session_id", params.session_id);
    return apiFetch<{
      period: string;
      gstin: string;
      ledger: Record<string, unknown>;
    }>(`${gstr3bPeriodPath(period)}/ledger-balance?${sp.toString()}`, {
      token,
    });
  },

  offsetPreview: (
    token: string,
    period: string,
    params: { client_gstin_id: string; session_id?: string | null }
  ) => {
    const sp = new URLSearchParams();
    sp.set("client_gstin_id", params.client_gstin_id);
    if (params.session_id) sp.set("session_id", params.session_id);
    return apiFetch<Gstr3bOffsetPreviewResponse>(
      `${gstr3bPeriodPath(period)}/offset-preview?${sp.toString()}`,
      { token, directBackend: true, cache: "no-store" }
    );
  },

  suggestOsupDet: (
    token: string,
    period: string,
    params: { client_gstin_id: string }
  ) => {
    const sp = new URLSearchParams();
    sp.set("client_gstin_id", params.client_gstin_id);
    return apiFetch<Gstr3bOsupDetSuggestionResponse>(
      `${gstr3bPeriodPath(period)}/suggestions/osup-det?${sp.toString()}`,
      { token, cache: "no-store" }
    );
  },

  suggestItcOth: (
    token: string,
    period: string,
    params: { client_gstin_id: string }
  ) => {
    const sp = new URLSearchParams();
    sp.set("client_gstin_id", params.client_gstin_id);
    return apiFetch<Gstr3bItcOthSuggestionResponse>(
      `${gstr3bPeriodPath(period)}/suggestions/itc-oth?${sp.toString()}`,
      { token, cache: "no-store" }
    );
  },

  save: (
    token: string,
    period: string,
    body: {
      client_gstin_id: string;
      period: string;
      session_id?: string | null;
      run_id?: string | null;
      save_body: Record<string, unknown>;
    }
  ) =>
    apiFetch<Gstr3bSaveResponse>(`${gstr3bPeriodPath(period)}/save`, {
      method: "POST",
      body: JSON.stringify(body),
      token,
    }),

  status: (
    token: string,
    period: string,
    params: {
      reference_id: string;
      session_id?: string | null;
      run_id?: string | null;
    }
  ) => {
    const sp = new URLSearchParams();
    sp.set("reference_id", params.reference_id);
    if (params.session_id) sp.set("session_id", params.session_id);
    if (params.run_id) sp.set("run_id", params.run_id);
    return apiFetch<Gstr3bStatusResponse>(
      `${gstr3bPeriodPath(period)}/status?${sp.toString()}`,
      {
        token,
        directBackend: true,
        timeoutMs: STATUS_POLL_REQUEST_TIMEOUT_MS,
        cache: "no-store",
      }
    );
  },

  offset: (
    token: string,
    period: string,
    body: {
      client_gstin_id: string;
      session_id?: string | null;
      run_id: string;
      pdcash: Gstr3bPdcashRow[];
      pditc: Gstr3bPditc;
    }
  ) =>
    apiFetch<Gstr3bOffsetResponse>(`${gstr3bPeriodPath(period)}/offset`, {
      method: "POST",
      body: JSON.stringify(body),
      token,
    }),

  evcOtp: (
    token: string,
    period: string,
    body: { pan: string; session_id?: string | null; run_id?: string | null }
  ) =>
    apiFetch<FilingEvcOtpResponse>(`${gstr3bPeriodPath(period)}/evc-otp`, {
      method: "POST",
      body: JSON.stringify(body),
      token,
    }),

  file: (
    token: string,
    period: string,
    body: {
      pan: string;
      otp: string;
      session_id?: string | null;
      run_id?: string | null;
      file_body?: Record<string, unknown> | null;
    }
  ) =>
    apiFetch<FilingFileResponse>(`${gstr3bPeriodPath(period)}/file`, {
      method: "POST",
      body: JSON.stringify(body),
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


// ─── IMS Action panel (Phase 3) ───────────────────────────────────────────────
// Recommendations + confirmed writeback. Never auto-called on page open.

export type ImsRecommendedActionDto = "accept" | "reject" | "hold";

export type ImsInvoiceRecommendationDto = {
  invoice_id: string;
  supplier_gstin: string;
  invoice_number: string;
  invoice_date?: string | null;
  supplier_name?: string | null;
  category: string;
  ims_status: string;
  recommended_action: ImsRecommendedActionDto;
  confidence_score: number | null;
  confidence_source?:
    | "matcher_fuzzy"
    | "matcher_exact_no_fuzzy_score"
    | "unavailable";
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
  invoices: ImsInvoiceRecommendationDto[];
};

export type ImsConfirmActionsResponse = {
  reference_id: string;
  transaction_id: string;
  invoice_count: number;
  action_groups: Record<string, number>;
  override_count: number;
  override_invoice_ids: string[];
  phase4_post_action_2b_sync_pending?: boolean;
  phase4_note?: string;
  run_id?: string;
  confirmation_summary?: string;
};

export type ImsActionStatusResponse = {
  reference_id: string;
  status_cd: string;
  is_complete: boolean;
  has_errors: boolean;
  processed_count: number;
  error_count: number;
  error_code?: string;
  error_message?: string;
  error_report?: Record<string, unknown>;
  outcome: "pending" | "confirmed" | "failed";
  run_id?: string;
};

export const imsApi = {
  /** Explicit Load only — never call from useEffect on mount. */
  getRecommendations: (token: string, runId: string) =>
    apiFetch<ImsRecommendationsResponse>(
      `/api/reconcile/runs/${encodeURIComponent(runId)}/ims/recommendations`,
      { token, cache: "no-store" }
    ),

  confirmActions: (
    token: string,
    runId: string,
    body: {
      confirmed: true;
      confirmation_summary: string;
      expected_count: number;
      invoices: Array<{
        invoice_id: string;
        chosen_action: ImsRecommendedActionDto;
        recommended_action?: string | null;
        section?: string;
        writeback_payload?: Record<string, unknown> | null;
        remarks?: string | null;
      }>;
    }
  ) =>
    apiFetch<ImsConfirmActionsResponse>(
      `/api/reconcile/runs/${encodeURIComponent(runId)}/ims/actions/confirm`,
      {
        method: "POST",
        body: JSON.stringify(body),
        token,
      }
    ),

  actionStatus: (token: string, runId: string, referenceId: string) => {
    const sp = new URLSearchParams();
    sp.set("reference_id", referenceId);
    return apiFetch<ImsActionStatusResponse>(
      `/api/reconcile/runs/${encodeURIComponent(runId)}/ims/actions/status?${sp.toString()}`,
      { token, cache: "no-store", timeoutMs: STATUS_POLL_REQUEST_TIMEOUT_MS }
    );
  },
};

// ─── E-Invoicing / Billing Module API Client ───────────────────────────────

export interface BillingCompanyProfile {
  id: string;
  client_gstin_id: string;
  legal_name: string;
  trade_name?: string | null;
  address_line1: string;
  address_line2?: string | null;
  city: string;
  state: string;
  state_code: string;
  pincode: string;
  gstin: string;
  pan?: string | null;
  bank_account_number?: string | null;
  bank_ifsc?: string | null;
  bank_name?: string | null;
  invoice_number_prefix: string;
  invoice_number_next_seq: number;
  financial_year_reset: boolean;
  created_at: string;
  updated_at: string;
}

export interface BillingCustomer {
  id: string;
  client_gstin_id: string;
  name: string;
  gstin?: string | null;
  address_line1: string;
  address_line2?: string | null;
  city: string;
  state: string;
  state_code: string;
  pincode: string;
  is_b2b: boolean;
  created_at: string;
  updated_at: string;
}

export interface BillingItem {
  id: string;
  client_gstin_id: string;
  name: string;
  hsn_or_sac_code: string;
  unit: string;
  default_rate: number; // paise
  default_tax_rate_percent: number;
  item_type: "goods" | "service";
  created_at: string;
  updated_at: string;
}

export interface BillingLineItemInput {
  item_id?: string | null;
  description: string;
  hsn_or_sac_code: string;
  quantity: number;
  unit: string;
  rate_paise: number;
  discount_percent: number;
  tax_rate_percent: number;
  cess_paise?: number;
}

export interface BillingLineItemResponse {
  id: string;
  invoice_id: string;
  item_id?: string | null;
  description: string;
  hsn_or_sac_code: string;
  quantity: number;
  unit: string;
  rate_paise: number;
  discount_percent: number;
  taxable_value_paise: number;
  cgst_rate_percent: number;
  cgst_paise: number;
  sgst_rate_percent: number;
  sgst_paise: number;
  igst_rate_percent: number;
  igst_paise: number;
  cess_paise: number;
  line_total_paise: number;
}

export interface BillingInvoice {
  id: string;
  client_gstin_id: string;
  company_profile_id: string;
  customer_id: string;
  invoice_number: string;
  invoice_date: string;
  due_date?: string | null;
  place_of_supply: string;
  is_interstate: boolean;
  subtotal_paise: number;
  total_tax_paise: number;
  total_paise: number;
  status: "draft" | "finalized" | "cancelled";
  irn?: string | null;
  notes?: string | null;
  created_at: string;
  updated_at: string;
  customer?: Partial<BillingCustomer> | null;
  company_profile?: BillingCompanyProfile | null;
  line_items?: BillingLineItemResponse[];
}

export const billingModuleApi = {
  // Company Profiles
  listCompanyProfiles: (token: string, clientGstinId: string) =>
    apiFetch<BillingCompanyProfile[]>(
      `/api/billing/masters/company-profiles?client_gstin_id=${encodeURIComponent(clientGstinId)}`,
      { token }
    ),

  getCompanyProfile: (token: string, id: string, clientGstinId: string) =>
    apiFetch<BillingCompanyProfile>(
      `/api/billing/masters/company-profiles/${encodeURIComponent(id)}?client_gstin_id=${encodeURIComponent(clientGstinId)}`,
      { token }
    ),

  createCompanyProfile: (token: string, data: Partial<BillingCompanyProfile>) =>
    apiFetch<BillingCompanyProfile>("/api/billing/masters/company-profiles", {
      method: "POST",
      body: JSON.stringify(data),
      token,
    }),

  updateCompanyProfile: (
    token: string,
    id: string,
    clientGstinId: string,
    data: Partial<BillingCompanyProfile>
  ) =>
    apiFetch<BillingCompanyProfile>(
      `/api/billing/masters/company-profiles/${encodeURIComponent(id)}?client_gstin_id=${encodeURIComponent(clientGstinId)}`,
      {
        method: "PUT",
        body: JSON.stringify(data),
        token,
      }
    ),

  // Customers
  listCustomers: (token: string, clientGstinId: string) =>
    apiFetch<BillingCustomer[]>(
      `/api/billing/masters/customers?client_gstin_id=${encodeURIComponent(clientGstinId)}`,
      { token }
    ),

  createCustomer: (token: string, data: Partial<BillingCustomer>) =>
    apiFetch<BillingCustomer>("/api/billing/masters/customers", {
      method: "POST",
      body: JSON.stringify(data),
      token,
    }),

  updateCustomer: (
    token: string,
    id: string,
    clientGstinId: string,
    data: Partial<BillingCustomer>
  ) =>
    apiFetch<BillingCustomer>(
      `/api/billing/masters/customers/${encodeURIComponent(id)}?client_gstin_id=${encodeURIComponent(clientGstinId)}`,
      {
        method: "PUT",
        body: JSON.stringify(data),
        token,
      }
    ),

  deleteCustomer: (token: string, id: string, clientGstinId: string) =>
    apiFetch<{ status: string }>(
      `/api/billing/masters/customers/${encodeURIComponent(id)}?client_gstin_id=${encodeURIComponent(clientGstinId)}`,
      {
        method: "DELETE",
        token,
      }
    ),

  // Items
  listItems: (token: string, clientGstinId: string) =>
    apiFetch<BillingItem[]>(
      `/api/billing/masters/items?client_gstin_id=${encodeURIComponent(clientGstinId)}`,
      { token }
    ),

  createItem: (token: string, data: Partial<BillingItem>) =>
    apiFetch<BillingItem>("/api/billing/masters/items", {
      method: "POST",
      body: JSON.stringify(data),
      token,
    }),

  updateItem: (
    token: string,
    id: string,
    clientGstinId: string,
    data: Partial<BillingItem>
  ) =>
    apiFetch<BillingItem>(
      `/api/billing/masters/items/${encodeURIComponent(id)}?client_gstin_id=${encodeURIComponent(clientGstinId)}`,
      {
        method: "PUT",
        body: JSON.stringify(data),
        token,
      }
    ),

  deleteItem: (token: string, id: string, clientGstinId: string) =>
    apiFetch<{ status: string }>(
      `/api/billing/masters/items/${encodeURIComponent(id)}?client_gstin_id=${encodeURIComponent(clientGstinId)}`,
      {
        method: "DELETE",
        token,
      }
    ),

  // Invoices
  listInvoices: (
    token: string,
    params: {
      client_gstin_id: string;
      status?: string;
      start_date?: string;
      end_date?: string;
    }
  ) => {
    const sp = new URLSearchParams();
    sp.set("client_gstin_id", params.client_gstin_id);
    if (params.status) sp.set("status", params.status);
    if (params.start_date) sp.set("start_date", params.start_date);
    if (params.end_date) sp.set("end_date", params.end_date);
    return apiFetch<BillingInvoice[]>(`/api/billing/invoices?${sp.toString()}`, {
      token,
    });
  },

  getInvoice: (token: string, id: string, clientGstinId: string) =>
    apiFetch<BillingInvoice>(
      `/api/billing/invoices/${encodeURIComponent(id)}?client_gstin_id=${encodeURIComponent(clientGstinId)}`,
      { token }
    ),

  createInvoice: (token: string, data: any) =>
    apiFetch<BillingInvoice>("/api/billing/invoices", {
      method: "POST",
      body: JSON.stringify(data),
      token,
    }),

  updateInvoice: (
    token: string,
    id: string,
    clientGstinId: string,
    data: any
  ) =>
    apiFetch<BillingInvoice>(
      `/api/billing/invoices/${encodeURIComponent(id)}?client_gstin_id=${encodeURIComponent(clientGstinId)}`,
      {
        method: "PATCH",
        body: JSON.stringify(data),
        token,
      }
    ),

  finalizeInvoice: (token: string, id: string, clientGstinId: string) =>
    apiFetch<BillingInvoice>(
      `/api/billing/invoices/${encodeURIComponent(id)}/finalize?client_gstin_id=${encodeURIComponent(clientGstinId)}`,
      {
        method: "POST",
        token,
      }
    ),
};

