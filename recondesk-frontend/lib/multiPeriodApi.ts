import { apiFetch } from "@/lib/api";

export type Gstr2bSource = "auto_fetch" | "manual_upload";
export type PrSource = "tally_bridge_existing" | "manual_upload" | "already_uploaded" | "missing";
export type ItemStatus = "pending" | "fetching" | "uploaded" | "queued" | "running" | "failed" | "completed";
export type BatchStatus = "pending" | "fetching" | "queued" | "running" | "partially_failed" | "completed" | "failed";

export interface MultiPeriodBatchItem {
  id: string;
  batch_id: string;
  period: string;
  gstr2b_source: Gstr2bSource | null;
  gstr2b_file_path: string | null;
  pr_source: PrSource | null;
  pr_file_path: string | null;
  reconciliation_run_id: string | null;
  status: ItemStatus;
  error_message: string | null;
  created_at: string;
  updated_at: string;
}

export interface MultiPeriodBatch {
  id: string;
  client_gstin_id: string;
  financial_year: string;
  status: BatchStatus;
  created_by: string | null;
  created_at: string;
  updated_at: string;
  items: MultiPeriodBatchItem[];
  summary?: Record<string, any>;
}

export interface PrStatusItem {
  period: string;
  pr_source: PrSource | null;
  pr_file_path: string | null;
  is_ready: boolean;
}

export interface PrStatusResponse {
  batch_id: string;
  financial_year: string;
  items: PrStatusItem[];
}

export async function createMultiPeriodBatch(
  clientId: string,
  financialYear: string,
  token: string
): Promise<MultiPeriodBatch> {
  return apiFetch<MultiPeriodBatch>("/api/multi-period/batches", {
    method: "POST",
    token,
    body: JSON.stringify({
      client_id: clientId,
      financial_year: financialYear,
    }),
  });
}

export async function triggerGstr2bAutofetch(
  batchId: string,
  token: string
): Promise<{ status: string; message: string }> {
  return apiFetch<{ status: string; message: string }>(
    `/api/multi-period/batches/${batchId}/fetch-gstr2b`,
    {
      method: "POST",
      token,
    }
  );
}

export async function checkPrStatus(
  batchId: string,
  token: string
): Promise<PrStatusResponse> {
  return apiFetch<PrStatusResponse>(
    `/api/multi-period/batches/${batchId}/pr-status`,
    {
      method: "GET",
      token,
    }
  );
}

export async function uploadManualPr(
  batchId: string,
  period: string,
  file: File,
  token: string
): Promise<MultiPeriodBatch> {
  const formData = new FormData();
  formData.append("file", file);

  return apiFetch<MultiPeriodBatch>(
    `/api/multi-period/batches/${batchId}/periods/${period}/upload-pr`,
    {
      method: "POST",
      token,
      body: formData,
    }
  );
}

export async function triggerBatchRun(
  batchId: string,
  token: string
): Promise<{ status: string; message: string }> {
  return apiFetch<{ status: string; message: string }>(
    `/api/multi-period/batches/${batchId}/run`,
    {
      method: "POST",
      token,
    }
  );
}

export async function getMultiPeriodBatch(
  batchId: string,
  token: string
): Promise<MultiPeriodBatch> {
  return apiFetch<MultiPeriodBatch>(
    `/api/multi-period/batches/${batchId}`,
    {
      method: "GET",
      token,
      directBackend: true,
    }
  );
}

export async function getBatchSummary(
  batchId: string,
  token: string
): Promise<MultiPeriodBatch> {
  return apiFetch<MultiPeriodBatch>(
    `/api/multi-period/batches/${batchId}/summary`,
    {
      method: "GET",
      token,
    }
  );
}

export async function listMultiPeriodBatches(
  clientId: string,
  token: string
): Promise<{ batches: MultiPeriodBatch[] }> {
  return apiFetch<{ batches: MultiPeriodBatch[] }>(
    `/api/multi-period/batches?client_id=${encodeURIComponent(clientId)}`,
    {
      method: "GET",
      token,
    }
  );
}

export async function downloadBatchExcelExport(
  batchId: string,
  token: string
): Promise<Blob> {
  const API_URL = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";
  const res = await fetch(`${API_URL}/api/multi-period/batches/${batchId}/export/excel`, {
    method: "GET",
    headers: {
      Authorization: `Bearer ${token}`,
    },
  });
  if (!res.ok) {
    throw new Error("Failed to download Excel export");
  }
  return res.blob();
}

