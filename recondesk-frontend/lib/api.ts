/**
 * Typed API client for the FastAPI backend (Railway).
 * Base URL is read from NEXT_PUBLIC_API_URL.
 */

import type {
  Database,
  ReconciliationStatus,
  MatchStatus,
} from "@/lib/supabase/types";

const API_URL = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

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

/** Profile from GET /api/v1/auth/me (matches FastAPI UserProfileResponse). */
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

export async function apiFetch<T>(
  path: string,
  options: RequestInit & { token?: string } = {}
): Promise<T> {
  const { token, ...fetchOptions } = options;

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

  const res = await fetch(`${API_URL}${path}`, {
    ...fetchOptions,
    headers,
  });

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

export interface ClientCreatePayload {
  gstin: string;
  trade_name: string;
  legal_name?: string | null;
  contact_name: string;
  contact_email: string;
  contact_phone: string;
  assigned_to?: string | null;
}

export const clientsApi = {
  list: (token: string) =>
    apiFetch<ClientGstin[]>("/api/clients", { token }),

  get: (token: string, id: string) =>
    apiFetch<ClientGstin>(`/api/clients/${id}`, { token }),

  create: (token: string, data: ClientCreatePayload) =>
    apiFetch<ClientGstin>("/api/clients", {
      method: "POST",
      body: JSON.stringify(data),
      token,
    }),

  update: (
    token: string,
    id: string,
    data: Database["public"]["Tables"]["client_gstins"]["Update"]
  ) =>
    apiFetch<ClientGstin>(`/api/clients/${id}`, {
      method: "PATCH",
      body: JSON.stringify(data),
      token,
    }),

  assign: (token: string, id: string, assigned_to: string) =>
    apiFetch<ClientGstin>(`/api/clients/${id}/assign`, {
      method: "PATCH",
      body: JSON.stringify({ assigned_to }),
      token,
    }),

  delete: (token: string, id: string) =>
    apiFetch<void>(`/api/clients/${id}`, { method: "DELETE", token }),
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

// ─── Team ─────────────────────────────────────────────────────────────────────

export const authApi = {
  /** Mounted at `/api/v1/auth` on the FastAPI backend. */
  me: (token: string) =>
    apiFetch<AuthMeProfile>("/api/v1/auth/me", { token }),
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

  pollStatus: (token: string, runId: string) =>
    apiFetch<RunPollStatus>(`/api/runs/${runId}/status`, { token }),

  retry: (token: string, runId: string) =>
    apiFetch<ImportWizardRun>(`/api/runs/${runId}/retry`, {
      method: "POST",
      token,
    }),
};
