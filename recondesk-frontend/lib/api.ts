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
export type TeamMember =
  Database["public"]["Tables"]["team_members"]["Row"];
export type UserProfile =
  Database["public"]["Tables"]["user_profiles"]["Row"];
export type Payment =
  Database["public"]["Tables"]["payments"]["Row"];

// ─── API-specific types ───────────────────────────────────────────────────────

export interface ApiError {
  detail: string;
  status: number;
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

async function apiFetch<T>(
  path: string,
  options: RequestInit & { token?: string } = {}
): Promise<T> {
  const { token, ...fetchOptions } = options;

  const headers: HeadersInit = {
    "Content-Type": "application/json",
    ...(token ? { Authorization: `Bearer ${token}` } : {}),
    ...(fetchOptions.headers ?? {}),
  };

  const res = await fetch(`${API_URL}${path}`, {
    ...fetchOptions,
    headers,
  });

  if (!res.ok) {
    let detail = `HTTP ${res.status}`;
    try {
      const json = await res.json();
      detail = json.detail ?? detail;
    } catch {
      // Response body was not JSON
    }
    throw { detail, status: res.status } satisfies ApiError;
  }

  if (res.status === 204) return undefined as unknown as T;

  return res.json() as Promise<T>;
}

// ─── Client GSTINs ───────────────────────────────────────────────────────────

export const clientsApi = {
  list: (token: string, page = 1, pageSize = 50) =>
    apiFetch<PaginatedResponse<ClientGstin>>(
      `/api/clients?page=${page}&page_size=${pageSize}`,
      { token }
    ),

  get: (token: string, id: string) =>
    apiFetch<ClientGstin>(`/api/clients/${id}`, { token }),

  create: (
    token: string,
    data: Database["public"]["Tables"]["client_gstins"]["Insert"]
  ) =>
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

export const teamApi = {
  list: (token: string) =>
    apiFetch<TeamMember[]>("/api/team", { token }),

  invite: (token: string, email: string, role: "Staff" | "Manager") =>
    apiFetch<TeamMember>("/api/team/invite", {
      method: "POST",
      body: JSON.stringify({ email, role }),
      token,
    }),

  remove: (token: string, memberId: string) =>
    apiFetch<void>(`/api/team/${memberId}`, { method: "DELETE", token }),
};

// ─── Health ───────────────────────────────────────────────────────────────────

export const healthApi = {
  ping: () => apiFetch<{ status: string }>("/health"),
};
