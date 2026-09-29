import { apiFetch, authApi, followupAuditApi, gstr3bApi } from "@/lib/api";
import type { Gstr3bReconciliationResult } from "@/lib/api";
import type { Rule37SummaryResponse } from "@/lib/rule37Summary";

type Paginated<T> = {
  data: T[];
  total: number;
  page: number;
  limit: number;
  total_pages: number;
};

export type ReportReconcileRow = {
  id: string;
  supplier_gstin: string;
  trade_name?: string | null;
  invoice_number: string;
  invoice_date: string;
  amount: number;
  decision_what: string | null;
  decision_why: string | null;
  decision_next: string | null;
  gstr2b_data: Record<string, string | number>;
  purchase_register_data: Record<string, string | number>;
  rule37_action_status?: "resolved" | "acknowledged" | null;
  rule37_urgency?: "CRITICAL" | "HIGH" | "MEDIUM";
  invoice_amount?: number;
  rule37_payment_coverage?: "full" | "partial" | null;
};

export type ReportSummary = {
  run_id: string;
  client_name: string;
  client_gstin?: string;
  period: string;
  assigned_to_name: string;
  status: string;
  total_gstr_records: number;
  matched_count: number;
  clean_matched_count?: number;
  itc_on_hold_count?: number;
  itc_on_hold_total_amount?: number;
  gross_matched_count?: number;
  gross_match_rate_pct?: number;
  missed_itc_count: number;
  missed_itc_total_amount: number;
  wrongful_risk_count: number;
  wrongful_risk_total_amount: number;
  match_rate_percent: number;
};

export type ReportConfidenceSummary = {
  run_id: string;
  total_invoices: number;
  high_confidence: number;
  medium_confidence: number;
  low_confidence: number;
  unmatched: number;
};

export type ReportPdfDataset = {
  summary: ReportSummary;
  generatedByName: string;
  riskRows: ReportReconcileRow[];
  itcRows: ReportReconcileRow[];
  rule37Rows: ReportReconcileRow[];
  rule37Summary: Rule37SummaryResponse;
  followupRows: Awaited<ReturnType<typeof followupAuditApi.listForRun>>;
  gstr3bResult: Gstr3bReconciliationResult | null;
  confidenceSummary: ReportConfidenceSummary | null;
};

export type ReconciliationReportFetchOptions = {
  /** Extra query string for ITC bucket pages (sort + filters, no page/limit). */
  itcFilterQuery?: string;
  /** Extra query string for risk bucket pages (sort + filters, no page/limit). */
  riskFilterQuery?: string;
};

function mergeBucketQuery(
  page: number,
  limit: number,
  filterQuery?: string
): string {
  const qs = new URLSearchParams(
    (filterQuery ?? "").replace(/^\?/, "").trim()
  );
  if (!qs.has("sort")) qs.set("sort", "amount_desc");
  qs.set("page", String(page));
  qs.set("limit", String(limit));
  return qs.toString();
}

async function fetchAllBucketRows(
  token: string,
  runId: string,
  bucket: "risk" | "itc",
  filterQuery?: string
): Promise<ReportReconcileRow[]> {
  const all: ReportReconcileRow[] = [];
  let page = 1;
  let totalPages = 1;
  const limit = 200;
  do {
    const qs = mergeBucketQuery(page, limit, filterQuery);
    const res = await apiFetch<Paginated<ReportReconcileRow>>(
      `/api/reconcile/runs/${encodeURIComponent(runId)}/${bucket}?${qs}`,
      { token }
    );
    all.push(...(res.data ?? []));
    totalPages = res.total_pages ?? 1;
    page += 1;
  } while (page <= totalPages);
  return all;
}

async function fetchAllRule37Rows(
  token: string,
  runId: string
): Promise<ReportReconcileRow[]> {
  const all: ReportReconcileRow[] = [];
  let page = 1;
  let totalPages = 1;
  const limit = 200;
  do {
    const res = await apiFetch<Paginated<ReportReconcileRow>>(
      `/api/reconcile/runs/${encodeURIComponent(runId)}/rule37?page=${page}&limit=${limit}`,
      { token }
    );
    all.push(...(res.data ?? []));
    totalPages = res.total_pages ?? 1;
    page += 1;
  } while (page <= totalPages);
  return all;
}

/** Fetch all data required to build the master reconciliation PDF. */
export async function fetchReconciliationReportData(
  token: string,
  runId: string,
  summary: ReportSummary,
  options?: ReconciliationReportFetchOptions
): Promise<ReportPdfDataset> {
  const [me, riskRows, itcRows, rule37Rows, rule37Summary, followupRows, gstr3bResult, confidenceSummary] =
    await Promise.all([
      authApi.me(token).catch(() => null),
      summary.wrongful_risk_count > 0
        ? fetchAllBucketRows(token, runId, "risk", options?.riskFilterQuery)
        : Promise.resolve([]),
      summary.missed_itc_count > 0
        ? fetchAllBucketRows(token, runId, "itc", options?.itcFilterQuery)
        : Promise.resolve([]),
      fetchAllRule37Rows(token, runId),
      apiFetch<Rule37SummaryResponse>(
        `/api/reconcile/runs/${encodeURIComponent(runId)}/rule37/summary`,
        { token }
      ),
      followupAuditApi.listForRun(token, runId),
      gstr3bApi.get(token, runId).catch(() => null),
      apiFetch<ReportConfidenceSummary>(
        `/api/reconcile/runs/${encodeURIComponent(runId)}/confidence-summary`,
        { token }
      ).catch(() => null),
    ]);

  const generatedByName =
    me?.full_name?.trim() || summary.assigned_to_name?.trim() || "—";

  return {
    summary,
    generatedByName,
    riskRows,
    itcRows,
    rule37Rows,
    rule37Summary,
    followupRows,
    gstr3bResult,
    confidenceSummary,
  };
}
