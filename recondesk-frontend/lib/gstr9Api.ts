import { apiFetch } from "@/lib/api";

export interface Gstr9Table4 {
  "4A_b2c": number;
  "4B_b2b": number;
  "4C_exports_paid": number;
  "4D_sez_paid": number;
  "4E_deemed_exports": number;
  "4F_advances": number;
  "4G_rcm_inward": number;
  "4N_total_taxable": number;
}

export interface Gstr9Table5 {
  "5A_exports_unpaid": number;
  "5B_sez_unpaid": number;
  "5C_rcm_outward": number;
  "5D_exempted": number;
  "5E_nil_rated": number;
  "5F_non_gst": number;
  "5N_total_exempted": number;
}

export interface Gstr9Table6 {
  "6A_total_3b_itc": number;
  "6B_b2b_inputs": number;
  "6C_rcm_unregistered": number;
  "6D_rcm_registered": number;
  "6E_import_goods": number;
  "6F_import_services": number;
}

export interface Gstr9Table7 {
  "7A_rule37": number;
  "7D_sec17_5": number;
  "7E_other_reversals": number;
  "7H_total_reversals": number;
}

export interface Gstr9Table8 {
  "8A_itc_2b": number;
  "8B_itc_3b": number;
  "8C_subsequent_fy": number;
  "8D_difference": number;
  "8E_itc_available_unavailed": number;
  "8F_itc_ineligible": number;
}

export interface Gstr9Table9 {
  igst_payable: number;
  igst_cash: number;
  igst_itc: number;
  cgst_payable: number;
  cgst_cash: number;
  cgst_itc: number;
  sgst_payable: number;
  sgst_cash: number;
  sgst_itc: number;
}

export interface Gstr9Computation {
  client_gstin_id: string;
  gstin: string;
  trade_name: string;
  financial_year: string;
  table4: Gstr9Table4;
  table5: Gstr9Table5;
  table6: Gstr9Table6;
  table7: Gstr9Table7;
  table8: Gstr9Table8;
  table9: Gstr9Table9;
  overrides_count: number;
}

export interface AuditOverrideInput {
  table_key: string;
  cell_key: string;
  override_value: number;
  notes?: string;
}

export interface Gstr9cReconciliation {
  client_gstin_id: string;
  gstin: string;
  trade_name: string;
  financial_year: string;
  part_ii_turnover: {
    "5A_audited_gross_turnover": number;
    "5P_reconciled_turnover": number;
    "5Q_gstr9_declared_turnover": number;
    "5R_unreconciled_turnover_variance": number;
  };
  part_iii_itc: {
    "12A_audited_itc": number;
    "12E_reconciled_itc": number;
    "12F_gstr9_declared_itc": number;
    "12G_unreconciled_itc_variance": number;
  };
  part_iv_tax_paid: {
    "14A_audited_tax_payable": number;
    "14P_gstr9_tax_paid": number;
    "14Q_unreconciled_tax_variance": number;
  };
  part_v_auditor_recommendation: {
    additional_turnover_tax: number;
    additional_itc_reversal_tax: number;
    total_recommended_payment: number;
  };
}

export async function fetchGstr9Computation(
  clientId: string,
  fy: string,
  token: string
): Promise<Gstr9Computation> {
  return apiFetch<Gstr9Computation>(
    `/api/gstr9/clients/${clientId}/computation?fy=${encodeURIComponent(fy)}`,
    {
      method: "GET",
      token,
    }
  );
}

export async function saveGstr9Overrides(
  clientId: string,
  fy: string,
  overrides: AuditOverrideInput[],
  token: string
): Promise<Gstr9Computation> {
  return apiFetch<Gstr9Computation>(`/api/gstr9/clients/${clientId}/overrides`, {
    method: "PATCH",
    token,
    body: JSON.stringify({
      client_id: clientId,
      financial_year: fy,
      overrides,
    }),
  });
}

export async function fetchGstr9cReconciliation(
  clientId: string,
  fy: string,
  auditedTurnover: number,
  auditedItc: number,
  auditedTax: number,
  token: string
): Promise<Gstr9cReconciliation> {
  const query = `fy=${encodeURIComponent(fy)}&audited_turnover=${auditedTurnover}&audited_itc=${auditedItc}&audited_tax=${auditedTax}`;
  return apiFetch<Gstr9cReconciliation>(
    `/api/gstr9c/clients/${clientId}/gstr9c/reconciliation?${query}`,
    {
      method: "GET",
      token,
    }
  );
}

export async function downloadGstr9Json(
  clientId: string,
  fy: string,
  token: string
): Promise<Blob> {
  const API_URL = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";
  const res = await fetch(
    `${API_URL}/api/gstr9/clients/${clientId}/export/json?fy=${encodeURIComponent(fy)}`,
    {
      method: "GET",
      headers: { Authorization: `Bearer ${token}` },
    }
  );
  if (!res.ok) throw new Error("Failed to download GSTR-9 JSON");
  return res.blob();
}

export async function downloadGstr9cJson(
  clientId: string,
  fy: string,
  auditedTurnover: number,
  auditedItc: number,
  auditedTax: number,
  token: string
): Promise<Blob> {
  const API_URL = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";
  const query = `fy=${encodeURIComponent(fy)}&audited_turnover=${auditedTurnover}&audited_itc=${auditedItc}&audited_tax=${auditedTax}`;
  const res = await fetch(
    `${API_URL}/api/gstr9c/clients/${clientId}/gstr9c/export/json?${query}`,
    {
      method: "GET",
      headers: { Authorization: `Bearer ${token}` },
    }
  );
  if (!res.ok) throw new Error("Failed to download GSTR-9C JSON");
  return res.blob();
}

export interface PeriodSyncDetail {
  period: string;
  month_label: string;
  status: "synced" | "partial_2b" | "partial_3b" | "partial_session" | "missing";
  has_2b: boolean;
  has_3b: boolean;
  has_session: boolean;
  reason: string;
}

export async function checkGstr9DataAvailability(
  clientId: string,
  fy: string,
  token: string
): Promise<{
  financial_year: string;
  total_periods: number;
  synced_periods_count: number;
  period_details: PeriodSyncDetail[];
  computation: Gstr9Computation;
}> {
  return apiFetch(
    `/api/gstr9/clients/${clientId}/availability?fy=${encodeURIComponent(fy)}`,
    {
      method: "POST",
      token,
    }
  );
}

export async function fetchLiveGstr9PortalApi(
  clientId: string,
  fy: string,
  token: string
): Promise<{
  financial_year: string;
  total_periods: number;
  synced_periods_count: number;
  period_details: PeriodSyncDetail[];
  computation: Gstr9Computation;
}> {
  return apiFetch(
    `/api/gstr9/clients/${clientId}/live-fetch?fy=${encodeURIComponent(fy)}`,
    {
      method: "POST",
      token,
    }
  );
}
