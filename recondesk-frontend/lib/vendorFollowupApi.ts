import { apiFetch } from "@/lib/api";

const API_URL = (process.env.NEXT_PUBLIC_API_URL ?? "https://api.recondesk.in").replace(/\/+$/, "");

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
  followup_status?: string | null;
  response_action?: string | null;
  arn_number?: string | null;
  promised_period?: string | null;
  token?: string | null;
  viewed_at?: string | null;
  promise_broken?: boolean;
  promise_broken_note?: string | null;
}

export interface VendorPortalInvoice {
  invoice_number: string;
  invoice_date?: string | null;
  taxable_value: number;
  tax_amount: number;
  reason: string;
}

export interface VendorPortalInfo {
  id: string;
  token: string;
  client_name: string;
  client_gstin: string;
  supplier_name: string;
  supplier_gstin: string;
  at_risk_itc_rupees: number;
  status: string;
  response_action?: string | null;
  arn_number?: string | null;
  promised_period?: string | null;
  dispute_reason?: string | null;
  attachment_key?: string | null;
  viewed_at?: string | null;
  responded_at?: string | null;
  expires_at?: string | null;
  invoices: VendorPortalInvoice[];
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
  portal_url?: string;
}

export interface EmailNoticeResponse {
  subject: string;
  html_body: string;
  supplier_gstin: string;
  portal_url?: string;
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
  token?: string | null;
  arn_number?: string | null;
  promised_period?: string | null;
  viewed_at?: string | null;
  responded_at?: string | null;
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
    trade_name?: string;
    contact_person?: string;
    vendor_phone?: string;
    at_risk_itc_rupees: number;
    template_type: string;
    custom_template?: string;
    portal_url?: string;
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
    trade_name?: string;
    contact_person?: string;
    at_risk_itc_rupees: number;
    template_type: string;
    custom_template?: string;
    portal_url?: string;
  },
  token: string
): Promise<EmailNoticeResponse> {
  return apiFetch(`/api/vendors/followup/clients/${clientId}/generate-email`, {
    method: "POST",
    body: JSON.stringify(payload),
    token,
  });
}

export async function generateVendorToken(
  clientId: string,
  payload: {
    supplier_gstin: string;
    supplier_name?: string;
    vendor_phone?: string;
    vendor_email?: string;
    at_risk_itc_rupees: number;
    template_type?: string;
    work_item_id?: string;
    channel?: string;
  },
  token: string
): Promise<{ token: string; portal_url: string; expires_at: string; invoices_count: number }> {
  return apiFetch(`/api/vendors/followup/clients/${clientId}/generate-token`, {
    method: "POST",
    body: JSON.stringify(payload),
    token,
  });
}

export async function updateVendorContact(
  clientId: string,
  supplierGstin: string,
  payload: { vendor_phone?: string; vendor_email?: string },
  token: string
): Promise<{ supplier_gstin: string; vendor_phone?: string; vendor_email?: string; message: string }> {
  return apiFetch(`/api/vendors/followup/clients/${clientId}/vendors/${supplierGstin}/contact`, {
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
    token?: string;
    expires_at?: string;
    invoices_snapshot?: any[];
  },
  token: string
): Promise<FollowupLog> {
  return apiFetch(`/api/vendors/followup/clients/${clientId}/dispatch`, {
    method: "POST",
    body: JSON.stringify(payload),
    token,
  });
}

export async function fetchVendorPortalData(token: string): Promise<VendorPortalInfo> {
  const res = await fetch(`${API_URL}/api/public/v/${encodeURIComponent(token)}`);
  if (!res.ok) {
    if (res.status === 404) throw new Error("Invalid or non-existent vendor reconciliation link.");
    if (res.status === 410) throw new Error("This vendor reconciliation link has expired (45-day validity period exceeded).");
    throw new Error(`Failed to load vendor portal details (${res.status})`);
  }
  return res.json();
}

export async function submitVendorPortalResponse(
  token: string,
  payload: {
    action: "ALREADY_FILED" | "PROMISED_NEXT_CYCLE" | "DISPUTED";
    arn_number?: string;
    promised_period?: string;
    dispute_reason?: string;
    attachment_key?: string;
  }
): Promise<{
  success: boolean;
  status: string;
  response_action: string;
  reference_id: string;
  token?: string;
  responded_at: string;
  arn_number?: string;
  promised_period?: string;
  dispute_reason?: string;
  attachment_key?: string;
  message: string;
}> {
  const res = await fetch(`${API_URL}/api/public/v/${encodeURIComponent(token)}/respond`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  if (!res.ok) {
    const err = await res.json().catch(() => null);
    throw new Error(err?.detail || `Submission failed (${res.status})`);
  }
  return res.json();
}

export async function uploadVendorPortalFile(
  token: string,
  file: File
): Promise<{ attachment_key: string; filename: string; file_size: number }> {
  const formData = new FormData();
  formData.append("file", file);
  const res = await fetch(`${API_URL}/api/public/v/${encodeURIComponent(token)}/upload`, {
    method: "POST",
    body: formData,
  });
  if (!res.ok) {
    const err = await res.json().catch(() => null);
    throw new Error(err?.detail || `File upload failed (${res.status})`);
  }
  return res.json();
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
