/**
 * Notice Defense & Reconciliation API client.
 */

import { apiFetch, resolveApiUrl } from "@/lib/api";

export interface NoticeDataInput {
  notice_reference: string;
  notice_type: string; // 'DRC-01C' | 'ASMT-10' | 'DRC-01B' | 'DRC-01A' | 'DRC-01' | 'OTHER'
  tax_period: string; // e.g. '032024'
  financial_year: string; // e.g. '2023-24'
  issue_date: string;
  reply_due_date: string;
  issuing_authority: string;
  alleged_tax_demand: number;
  alleged_igst: number;
  alleged_cgst: number;
  alleged_sgst: number;
  alleged_cess: number;
  discrepancy_category: string;
}

export interface DefenseSummary {
  alleged_total: number;
  timing_diff_itc: number;
  reclaimed_rule37_itc: number;
  table4b_reversals_itc: number;
  total_explained: number;
  unexplained_balance: number;
  reconciled_pct: number;
  reconciliation_status: "FULLY_RECONCILED" | "PARTIALLY_EXPLAINED" | string;
  supporting_invoices_count: number;
  run_quality_status?: string;
  run_integrity_warnings?: string[];
  is_anomalous?: boolean;
}

export interface InvoiceScheduleItem {
  supplier_gstin: string;
  supplier_name: string;
  invoice_number: string;
  invoice_date: string;
  taxable_value: number;
  igst: number;
  cgst: number;
  sgst: number;
  total_tax: number;
  defense_ground: string;
  legal_basis: string;
}

export interface NoticeDefenseResult {
  client_name: string;
  client_gstin: string;
  notice_reference: string;
  notice_type: string;
  tax_period: string;
  issue_date: string;
  issuing_authority: string;
  reconciliation_run_id?: string | null;
  alleged_tax_demand: number;
  alleged_igst: number;
  alleged_cgst: number;
  alleged_sgst: number;
  alleged_cess: number;
  defense_summary: DefenseSummary;
  run_quality_status?: string;
  run_integrity_warnings?: string[];
  is_anomalous?: boolean;
  invoices_schedule: InvoiceScheduleItem[];
  formal_reply_text: string;
}

export interface SavedNoticeRecord {
  id: string;
  client_gstin_id: string;
  notice_reference: string;
  notice_type: string;
  tax_period: string;
  financial_year?: string;
  issue_date: string;
  reply_due_date?: string;
  issuing_authority?: string;
  alleged_tax_demand: number;
  alleged_igst: number;
  alleged_cgst: number;
  alleged_sgst: number;
  status: string;
  defense_summary?: DefenseSummary;
  invoices_schedule?: InvoiceScheduleItem[];
  formal_reply_text?: string;
  created_at: string;
}

export interface MatchingReconRun {
  id: string;
  period: string;
  status: string;
  total_records: number;
  gstr_records_imported: number;
  pr_records_imported: number;
  created_at: string;
  summary?: any;
}

/**
 * Upload and extract text / DIN / demand amounts from notice PDF.
 */
export async function parseNoticePdf(
  file: File,
  token?: string
): Promise<{ success: boolean; notice: Partial<NoticeDataInput> }> {
  const formData = new FormData();
  formData.append("file", file);

  return apiFetch<{ success: boolean; notice: Partial<NoticeDataInput> }>(
    "/api/notices/parse-pdf",
    {
      method: "POST",
      body: formData,
      token,
    }
  );
}

/**
 * Find matching reconciliation runs for a client by period.
 */
export async function getMatchingRuns(
  clientId: string,
  period?: string,
  fy?: string,
  token?: string
): Promise<{ client_id: string; runs: MatchingReconRun[] }> {
  const params = new URLSearchParams();
  if (period) params.set("period", period);
  if (fy) params.set("fy", fy);

  return apiFetch<{ client_id: string; runs: MatchingReconRun[] }>(
    `/api/notices/matching-runs/${encodeURIComponent(clientId)}?${params.toString()}`,
    { token }
  );
}

/**
 * Compute the mathematical reconciliation defense and formal reply letter.
 */
export async function analyzeNoticeDefense(
  clientId: string,
  noticeData: NoticeDataInput,
  reconciliationRunId?: string | null,
  token?: string
): Promise<{ success: boolean; defense: NoticeDefenseResult }> {
  return apiFetch<{ success: boolean; defense: NoticeDefenseResult }>(
    "/api/notices/analyze-defense",
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        client_id: clientId,
        notice_data: noticeData,
        reconciliation_run_id: reconciliationRunId || null,
      }),
      token,
    }
  );
}

/**
 * Save notice and defense record in client workspace.
 */
export async function saveNoticeRecord(
  payload: {
    client_id: string;
    notice_data: NoticeDataInput;
    reconciliation_run_id?: string | null;
    defense_summary?: DefenseSummary;
    invoices_schedule?: InvoiceScheduleItem[];
    formal_reply_text?: string;
    status?: string;
  },
  token?: string
): Promise<{ success: boolean; notice: SavedNoticeRecord }> {
  return apiFetch<{ success: boolean; notice: SavedNoticeRecord }>("/api/notices", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
    token,
  });
}

/**
 * List notices for a specific client.
 */
export async function listClientNotices(
  clientId: string,
  token?: string
): Promise<{ client_id: string; notices: SavedNoticeRecord[] }> {
  return apiFetch<{ client_id: string; notices: SavedNoticeRecord[] }>(
    `/api/notices/client/${encodeURIComponent(clientId)}`,
    { token }
  );
}

/**
 * Retrieve full details of a saved notice.
 */
export async function getNotice(
  noticeId: string,
  token?: string
): Promise<{ notice: SavedNoticeRecord }> {
  return apiFetch<{ notice: SavedNoticeRecord }>(
    `/api/notices/${encodeURIComponent(noticeId)}`,
    { token }
  );
}

/**
 * Update notice status.
 */
export async function updateNoticeStatus(
  noticeId: string,
  status: string,
  token?: string
): Promise<{ success: boolean }> {
  return apiFetch<{ success: boolean }>(
    `/api/notices/${encodeURIComponent(noticeId)}/status`,
    {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ status }),
      token,
    }
  );
}

/**
 * Export and download defense Excel workbook.
 */
export async function downloadDefenseExcel(
  defenseData: NoticeDefenseResult | any,
  token?: string
): Promise<void> {
  const headers: Record<string, string> = { "Content-Type": "application/json" };
  if (token) {
    headers["Authorization"] = `Bearer ${token}`;
  }
  const res = await fetch(resolveApiUrl("/api/notices/export-excel"), {
    method: "POST",
    headers,
    body: JSON.stringify(defenseData),
  });

  if (!res.ok) {
    throw new Error(`Failed to export Excel (HTTP ${res.status})`);
  }

  const blob = await res.blob();
  const url = window.URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  const ref = defenseData.notice_reference || "Notice_Defense";
  a.download = `GST_Notice_Defense_Annexure_${ref}.xlsx`;
  document.body.appendChild(a);
  a.click();
  document.body.removeChild(a);
  window.URL.revokeObjectURL(url);
}
