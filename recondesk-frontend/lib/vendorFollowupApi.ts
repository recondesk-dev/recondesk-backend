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
