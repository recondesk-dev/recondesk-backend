import { apiFetch } from "@/lib/api";

export interface VendorRiskSummary {
  supplier_gstin: string;
  supplier_name: string;
  vendor_phone: string;
  vendor_email: string;
  total_invoices: number;
  mismatch_count: number;
  rule37_count: number;
  rule37_at_risk_rupees: number;
  at_risk_itc_rupees: number;
  risk_score: number;
  last_followup_at: string | null;
  followup_count: number;
}

export interface VendorFollowupResponse {
  client_gstin_id: string;
  total_high_risk_vendors: number;
  total_at_risk_itc_rupees: number;
  vendors: VendorRiskSummary[];
}

export interface WhatsAppPayloadResponse {
  supplier_gstin: string;
  supplier_name: string;
  vendor_phone: string;
  template_type: string;
  message_text: string;
  whatsapp_url: string;
}

export interface EmailNoticeResponse {
  subject: string;
  html_body: string;
  supplier_gstin: string;
}

export interface FollowupLog {
  id: string;
  client_gstin_id: string;
  supplier_gstin: string;
  supplier_name: string;
  vendor_phone: string;
  vendor_email: string;
  channel: string;
  template_type: string;
  at_risk_itc_rupees: number;
  status: string;
  dispatched_at: string;
  work_item_id?: string | null;
  message_body?: string | null;
}

export interface WorkItemVendorProfile {
  work_item_id: string;
  vendor_gstin: string;
  vendor_name: string;
  risk_score: number;
  risk_tier: string;
  total_invoices: number;
  mismatch_count: number;
  mismatch_rate: number;
  rule37_open_count: number;
  rule37_at_risk: number;
  section_17_5_count: number;
  late_filing_count: number;
  pr_only_count: number;
  open_work_item_count: number;
  itc_at_stake: number;
}

export interface VendorResponsePayload {
  response_category: string;
  contact_channel?: string;
  contact_person?: string;
  promised_date?: string | null;
  notes?: string;
  evidence_storage_key?: string | null;
  evidence_filename?: string | null;
  target_status?: string | null;
}

export async function fetchVendorRiskSummaries(
  clientId: string,
  token: string
): Promise<VendorFollowupResponse> {
  return apiFetch(`/api/vendors/followup/clients/${clientId}`, { token });
}

export async function generateWhatsAppLink(
  clientId: string,
  payload: {
    supplier_gstin: string;
    supplier_name?: string;
    vendor_phone?: string;
    at_risk_itc_rupees: number;
    template_type: string;
  },
  token: string
): Promise<WhatsAppPayloadResponse> {
  return apiFetch(`/api/vendors/followup/clients/${clientId}/generate-whatsapp`, {
    method: "POST",
    body: JSON.stringify(payload),
    token,
  });
}

export async function generateEmailNotice(
  clientId: string,
  payload: {
    supplier_gstin: string;
    supplier_name?: string;
    at_risk_itc_rupees: number;
    template_type: string;
  },
  token: string
): Promise<EmailNoticeResponse> {
  return apiFetch(`/api/vendors/followup/clients/${clientId}/generate-email`, {
    method: "POST",
    body: JSON.stringify(payload),
    token,
  });
}

export async function logFollowupDispatch(
  clientId: string,
  payload: {
    supplier_gstin: string;
    supplier_name?: string;
    vendor_phone?: string;
    vendor_email?: string;
    channel: string;
    template_type: string;
    at_risk_itc_rupees: number;
    work_item_id?: string;
    message_body?: string;
  },
  token: string
): Promise<FollowupLog> {
  return apiFetch(`/api/vendors/followup/clients/${clientId}/dispatch`, {
    method: "POST",
    body: JSON.stringify(payload),
    token,
  });
}

export async function fetchFollowupHistory(
  clientId: string,
  token: string
): Promise<{ client_gstin_id: string; total_logs: number; logs: FollowupLog[] }> {
  return apiFetch(`/api/vendors/followup/clients/${clientId}/history`, { token });
}

export async function fetchWorkItemFollowupHistory(
  workItemId: string,
  token: string
): Promise<{ work_item_id: string; client_gstin_id: string; total_logs: number; logs: FollowupLog[] }> {
  return apiFetch(`/api/vendors/followup/work-items/${workItemId}/history`, { token });
}

export async function fetchWorkItemVendorProfile(
  workItemId: string,
  token: string
): Promise<WorkItemVendorProfile> {
  return apiFetch(`/api/work-items/${workItemId}/vendor-profile`, { token });
}

export async function recordVendorResponse(
  workItemId: string,
  payload: VendorResponsePayload,
  token: string
): Promise<any> {
  return apiFetch(`/api/work-items/${workItemId}/vendor-response`, {
    method: "POST",
    body: JSON.stringify(payload),
    token,
  });
}

export async function scheduleWorkItemFollowup(
  workItemId: string,
  payload: { due_at?: string | null; note?: string },
  token: string
): Promise<any> {
  return apiFetch(`/api/work-items/${workItemId}/schedule-followup`, {
    method: "POST",
    body: JSON.stringify(payload),
    token,
  });
}
