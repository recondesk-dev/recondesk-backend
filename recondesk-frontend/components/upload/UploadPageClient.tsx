"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import type { SupabaseClient } from "@supabase/supabase-js";
import { createClient } from "@/lib/supabase/client";
import { Logo } from "@/components/ui/Logo";

type UploadRequest = {
  id: string;
  title: string;
  description: string | null;
  expires_at: string | null;
  client_name?: string | null;
  client_gstin?: string | null;
  firm_name?: string | null;
  firm_city?: string | null;
  ca_name?: string | null;
  created_at?: string | null;
};

type FileStatus = "pending" | "uploading" | "done" | "failed";

type UploadedFile = {
  file: File;
  status: FileStatus;
  error: string | null;
  progress: number;
};

type PageState =
  | "validating"
  | "invalid"
  | "expired"
  | "ready"
  | "uploading"
  | "success"
  | "partial_failure";

type FileQueueItem = UploadedFile & { id: string };

type UploadedFileRecord = {
  id: string;
  upload_request_id: string;
  filename: string;
  file_size: number;
  mime_type: string;
  public_url: string;
  created_at: string;
};

type UploadedFileInsert = Omit<UploadedFileRecord, "id" | "created_at">;

type PresignedUrlResponse = {
  upload_url: string;
  public_url: string;
};

const API_URL = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";
const MAX_FILE_SIZE = 26214400; // 25 MB

const ALLOWED_EXTENSIONS = [".xlsx", ".csv", ".pdf", ".zip"] as const;

const ALLOWED_MIME_TYPES = new Set([
  "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
  "text/csv",
  "application/pdf",
  "application/zip",
  "application/x-zip-compressed",
]);

function getSupabaseClient(): SupabaseClient {
  return createClient() as SupabaseClient;
}

function formatFileSize(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

function formatExpiryDate(isoString: string | null | undefined): string | null {
  if (!isoString) return null;
  try {
    const d = new Date(isoString);
    if (isNaN(d.getTime())) return null;
    return d.toLocaleDateString("en-IN", {
      day: "numeric",
      month: "short",
      year: "numeric",
    });
  } catch {
    return null;
  }
}

function inferContentType(filename: string): string {
  const lower = filename.toLowerCase();
  if (lower.endsWith(".xlsx")) {
    return "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet";
  }
  if (lower.endsWith(".csv")) return "text/csv";
  if (lower.endsWith(".pdf")) return "application/pdf";
  if (lower.endsWith(".zip")) return "application/zip";
  return "application/octet-stream";
}

function hasAllowedExtension(filename: string): boolean {
  const lower = filename.toLowerCase();
  return ALLOWED_EXTENSIONS.some((ext) => lower.endsWith(ext));
}

function validateFile(file: File): string | null {
  if (!hasAllowedExtension(file.name)) {
    return "Only .xlsx, .csv, .pdf, and .zip files are allowed.";
  }
  const mime = file.type || inferContentType(file.name);
  if (!ALLOWED_MIME_TYPES.has(mime)) {
    return "File type is not supported.";
  }
  if (file.size > MAX_FILE_SIZE) {
    return "File exceeds the 25 MB size limit.";
  }
  return null;
}

async function parseErrorMessage(res: Response): Promise<string> {
  try {
    const body = (await res.json()) as unknown;
    if (typeof body === "object" && body !== null && "detail" in body) {
      const detail = (body as { detail: unknown }).detail;
      if (typeof detail === "string") return detail;
    }
  } catch {
    // ignore JSON parse errors
  }
  return `Request failed (${res.status})`;
}

function CheckIcon({ className }: { className?: string }) {
  return (
    <svg className={className} viewBox="0 0 20 20" fill="currentColor" aria-hidden>
      <path
        fillRule="evenodd"
        d="M16.707 5.293a1 1 0 010 1.414l-8 8a1 1 0 01-1.414 0l-4-4a1 1 0 011.414-1.414L8 12.586l7.293-7.293a1 1 0 011.414 0z"
        clipRule="evenodd"
      />
    </svg>
  );
}

function XIcon({ className }: { className?: string }) {
  return (
    <svg className={className} viewBox="0 0 20 20" fill="currentColor" aria-hidden>
      <path
        fillRule="evenodd"
        d="M4.293 4.293a1 1 0 011.414 0L10 8.586l4.293-4.293a1 1 0 111.414 1.414L11.414 10l4.293 4.293a1 1 0 01-1.414 1.414L10 11.414l-4.293 4.293a1 1 0 01-1.414-1.414L8.586 10 4.293 5.707a1 1 0 010-1.414z"
        clipRule="evenodd"
      />
    </svg>
  );
}

function ValidatingSkeleton() {
  return (
    <div className="animate-pulse space-y-6">
      <div className="h-7 w-48 rounded-full bg-gray-100" />
      <div className="h-4 w-full rounded-full bg-gray-100" />
      <div className="h-4 w-3/4 rounded-full bg-gray-100" />
      <div className="h-32 w-full rounded-2xl bg-gray-100" />
    </div>
  );
}

export default function UploadPageClient({ token }: { token: string }) {
  const [pageState, setPageState] = useState<PageState>("validating");
  const [uploadRequest, setUploadRequest] = useState<UploadRequest | null>(null);
  const [fileQueue, setFileQueue] = useState<FileQueueItem[]>([]);
  const [dropError, setDropError] = useState<string | null>(null);
  const [isDragOver, setIsDragOver] = useState(false);
  const dragCounter = useRef(0);
  const fileInputRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    let cancelled = false;

    async function validateToken(): Promise<void> {
      try {
        // Fetch full branding and client metadata from backend
        const res = await fetch(`${API_URL}/upload/info/${encodeURIComponent(token)}`);
        if (res.ok) {
          const info = (await res.json()) as UploadRequest & { is_expired?: boolean };
          if (cancelled) return;
          if (info.is_expired) {
            setPageState("expired");
            return;
          }
          setUploadRequest(info);
          setPageState("ready");
          return;
        }

        if (res.status === 404) {
          setPageState("invalid");
          return;
        }

        if (res.status === 410) {
          setPageState("expired");
          return;
        }

        // Fallback to direct Supabase query if backend request is non-200
        const supabase = getSupabaseClient();
        const { data, error } = await supabase
          .from("upload_requests")
          .select("id, title, description, expires_at")
          .eq("token", token)
          .single();

        if (cancelled) return;

        if (error || !data) {
          setPageState("invalid");
          return;
        }

        const request = data as UploadRequest;
        if (request.expires_at && new Date(request.expires_at) < new Date()) {
          setPageState("expired");
          return;
        }

        setUploadRequest(request);
        setPageState("ready");
      } catch {
        if (!cancelled) {
          // In case of network errors reaching backend, attempt direct Supabase fallback
          try {
            const supabase = getSupabaseClient();
            const { data, error } = await supabase
              .from("upload_requests")
              .select("id, title, description, expires_at")
              .eq("token", token)
              .single();
            if (data && !error) {
              const request = data as UploadRequest;
              if (request.expires_at && new Date(request.expires_at) < new Date()) {
                setPageState("expired");
                return;
              }
              setUploadRequest(request);
              setPageState("ready");
              return;
            }
          } catch {
            /* ignore fallback error */
          }
          setPageState("invalid");
        }
      }
    }

    void validateToken();

    return () => {
      cancelled = true;
    };
  }, [token]);

  const addFiles = useCallback(
    (incoming: FileList | File[]) => {
      if (pageState !== "ready") return;

      const files = Array.from(incoming);
      const errors: string[] = [];
      const accepted: FileQueueItem[] = [];

      for (const file of files) {
        const validationError = validateFile(file);
        if (validationError) {
          errors.push(`${file.name}: ${validationError}`);
          continue;
        }

        const duplicate = fileQueue.some(
          (item) => item.file.name === file.name && item.file.size === file.size
        );
        if (duplicate) {
          errors.push(`${file.name}: already added`);
          continue;
        }

        accepted.push({
          id: crypto.randomUUID(),
          file,
          status: "pending",
          error: null,
          progress: 0,
        });
      }

      if (accepted.length > 0) {
        setFileQueue((prev) => [...prev, ...accepted]);
      }

      setDropError(errors.length > 0 ? errors[0] : null);
    },
    [fileQueue, pageState]
  );

  const removeFile = useCallback((id: string) => {
    setFileQueue((prev) => prev.filter((item) => item.id !== id));
  }, []);

  function uploadFileItem(
    uploadRequestId: string,
    item: FileQueueItem,
    onProgress: (pct: number) => void
  ): Promise<{ ok: boolean; error: string | null }> {
    return new Promise((resolve) => {
      (async () => {
        try {
          const contentType = item.file.type || inferContentType(item.file.name);

          const presignRes = await fetch(`${API_URL}/upload/presigned-url`, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({
              token,
              filename: item.file.name,
              content_type: contentType,
            }),
          });

          if (!presignRes.ok) {
            throw new Error(await parseErrorMessage(presignRes));
          }

          const presignData = (await presignRes.json()) as PresignedUrlResponse;
          if (!presignData.upload_url || !presignData.public_url) {
            throw new Error("Invalid presigned URL response from server.");
          }

          const xhr = new XMLHttpRequest();
          xhr.open("PUT", presignData.upload_url, true);
          xhr.setRequestHeader("Content-Type", contentType);

          xhr.upload.onprogress = (evt) => {
            if (evt.lengthComputable) {
              const pct = Math.min(100, Math.round((evt.loaded / evt.total) * 100));
              onProgress(pct);
            }
          };

          xhr.onload = async () => {
            if (xhr.status >= 200 && xhr.status < 300) {
              try {
                const supabase = getSupabaseClient();
                const fileInsert: UploadedFileInsert = {
                  upload_request_id: uploadRequestId,
                  filename: item.file.name,
                  file_size: item.file.size,
                  mime_type: contentType,
                  public_url: presignData.public_url,
                };
                const { error: insertError } = await supabase
                  .from("uploaded_files")
                  .insert(fileInsert);

                if (insertError) {
                  resolve({ ok: false, error: insertError.message });
                  return;
                }
                onProgress(100);
                resolve({ ok: true, error: null });
              } catch (e) {
                const msg = e instanceof Error ? e.message : "Database record failed";
                resolve({ ok: false, error: msg });
              }
            } else {
              resolve({ ok: false, error: `Upload failed (${xhr.status})` });
            }
          };

          xhr.onerror = () => {
            resolve({ ok: false, error: "Network error during file upload" });
          };

          xhr.send(item.file);
        } catch (err: unknown) {
          const message = err instanceof Error ? err.message : "Upload failed";
          resolve({ ok: false, error: message });
        }
      })();
    });
  }

  async function runUploads(items: FileQueueItem[]): Promise<void> {
    if (!uploadRequest || items.length === 0) return;

    const itemIds = new Set(items.map((item) => item.id));

    setPageState("uploading");
    setDropError(null);
    setFileQueue((prev) =>
      prev.map((entry) =>
        itemIds.has(entry.id)
          ? { ...entry, status: "uploading", error: null, progress: 5 }
          : entry
      )
    );

    const results = await Promise.allSettled(
      items.map(async (item) => {
        const result = await uploadFileItem(uploadRequest.id, item, (pct) => {
          setFileQueue((prev) =>
            prev.map((entry) =>
              entry.id === item.id ? { ...entry, progress: pct } : entry
            )
          );
        });
        return { id: item.id, ...result };
      })
    );

    setFileQueue((prev) => {
      const resultById = new Map<string, { ok: boolean; error: string | null }>();

      for (const result of results) {
        if (result.status === "fulfilled") {
          resultById.set(result.value.id, {
            ok: result.value.ok,
            error: result.value.error,
          });
        }
      }

      const next = prev.map((entry) => {
        const uploadResult = resultById.get(entry.id);
        if (!uploadResult) return entry;

        if (uploadResult.ok) {
          return { ...entry, status: "done" as const, progress: 100, error: null };
        }

        return {
          ...entry,
          status: "failed" as const,
          error: uploadResult.error ?? "Upload failed",
        };
      });

      const hasFailed = next.some((entry) => entry.status === "failed");
      const allDone = next.length > 0 && next.every((entry) => entry.status === "done");

      setPageState(allDone && !hasFailed ? "success" : "partial_failure");
      return next;
    });
  }

  function handleUploadAll(): void {
    const pendingItems = fileQueue.filter((item) => item.status === "pending");
    void runUploads(pendingItems);
  }

  function handleRetry(id: string): void {
    const item = fileQueue.find((entry) => entry.id === id);
    if (!item || item.status !== "failed" || !uploadRequest) return;
    void runUploads([item]);
  }

  const pendingCount = fileQueue.filter((item) => item.status === "pending").length;
  const doneFiles = fileQueue.filter((item) => item.status === "done");
  const totalDoneBytes = useMemo(
    () => doneFiles.reduce((acc, curr) => acc + curr.file.size, 0),
    [doneFiles]
  );

  const firmName = uploadRequest?.firm_name || "Chartered Accountants";
  const firmInitial = (firmName.trim()[0] || "C").toUpperCase();
  const submissionRef = uploadRequest ? `REC-${uploadRequest.id.slice(0, 8).toUpperCase()}` : "";
  const expiryLabel = formatExpiryDate(uploadRequest?.expires_at);

  return (
    <div className="recondesk-textured-bg min-h-screen py-10 px-4">
      <div className="mx-auto max-w-xl">
        {/* Brand & Security Header */}
        <div className="mb-6 flex items-center justify-between">
          <Logo width={160} height={32} />
          <div className="flex items-center gap-2 rounded-full border border-gray-200/80 bg-white/80 px-3 py-1 text-xs text-gray-500 shadow-sm backdrop-blur-sm">
            <span className="h-2 w-2 rounded-full bg-emerald-500 animate-pulse" />
            <span className="font-medium text-gray-700">Encrypted Portal</span>
          </div>
        </div>

        {/* Firm Profile Banner */}
        <div className="mb-6 rounded-2xl border border-gray-200/80 bg-white p-5 shadow-[var(--shadow-soft)]">
          <div className="flex items-center gap-3.5">
            <div className="flex h-12 w-12 shrink-0 items-center justify-center rounded-2xl bg-[var(--ink)] text-lg font-bold text-white shadow-sm">
              {firmInitial}
            </div>
            <div className="min-w-0 flex-1">
              <div className="flex flex-wrap items-center gap-2">
                <h2 className="truncate text-base font-semibold tracking-tight text-[var(--ink)]">
                  {firmName}
                </h2>
                <span className="inline-flex items-center rounded-full bg-blue-50 px-2 py-0.5 text-[10px] font-semibold text-blue-700 border border-blue-200/60">
                  Verified CA
                </span>
              </div>
              <p className="mt-0.5 text-xs text-gray-500">
                {uploadRequest?.ca_name ? `Requested by ${uploadRequest.ca_name}` : "Professional Accounting & Tax Services"}
                {uploadRequest?.firm_city ? ` · ${uploadRequest.firm_city}` : ""}
              </p>
            </div>
          </div>
        </div>

        {/* Main Action Container */}
        <div className="rounded-2xl border border-gray-200/80 bg-white p-6 sm:p-8 shadow-[var(--shadow-soft)]">
          {pageState === "validating" && <ValidatingSkeleton />}

          {pageState === "invalid" && (
            <div className="text-center py-6">
              <div className="mx-auto flex h-14 w-14 items-center justify-center rounded-full bg-red-50 text-red-600">
                <XIcon className="h-7 w-7" />
              </div>
              <h1 className="mt-4 text-lg font-semibold text-gray-900">
                Upload Link Not Found
              </h1>
              <p className="mt-2 text-sm text-gray-600 max-w-sm mx-auto">
                This document request link is invalid or has been revoked by your accounting firm. Please contact your CA for an updated link.
              </p>
            </div>
          )}

          {pageState === "expired" && (
            <div className="text-center py-6">
              <div className="mx-auto flex h-14 w-14 items-center justify-center rounded-full bg-amber-50 text-amber-600">
                <XIcon className="h-7 w-7" />
              </div>
              <h1 className="mt-4 text-lg font-semibold text-gray-900">
                Upload Link Expired
              </h1>
              <p className="mt-2 text-sm text-gray-600 max-w-sm mx-auto">
                This document request has passed its submission deadline. Please reach out to{" "}
                <span className="font-semibold text-gray-900">{firmName}</span> to request a refreshed upload link.
              </p>
            </div>
          )}

          {pageState === "success" && (
            <div className="space-y-6">
              <div className="flex items-start gap-4">
                <div className="flex h-12 w-12 shrink-0 items-center justify-center rounded-full bg-emerald-100 text-emerald-600">
                  <CheckIcon className="h-6 w-6" />
                </div>
                <div>
                  <h1 className="text-xl font-bold tracking-tight text-[var(--ink)]">
                    Documents Submitted Successfully
                  </h1>
                  <p className="mt-1 text-sm text-gray-600">
                    Your files have been securely transmitted to{" "}
                    <span className="font-semibold text-gray-900">{firmName}</span>.
                  </p>
                </div>
              </div>

              {/* Digital Submission Receipt Card */}
              <div className="rounded-xl border border-gray-200/90 bg-[#FBFBFC] p-4 text-xs space-y-3">
                <div className="flex items-center justify-between border-b border-gray-200/70 pb-2">
                  <span className="font-medium text-gray-500 uppercase tracking-wider text-[10px]">
                    Submission Receipt
                  </span>
                  <span className="font-mono font-semibold text-[var(--ink)] bg-white px-2 py-0.5 rounded border border-gray-200">
                    {submissionRef}
                  </span>
                </div>
                <div className="grid grid-cols-2 gap-2 text-gray-600">
                  <div>
                    <span className="text-gray-400">Total Files:</span>{" "}
                    <strong className="text-gray-800">{doneFiles.length}</strong>
                  </div>
                  <div>
                    <span className="text-gray-400">Total Size:</span>{" "}
                    <strong className="text-gray-800">{formatFileSize(totalDoneBytes)}</strong>
                  </div>
                  {uploadRequest?.client_gstin ? (
                    <div className="col-span-2">
                      <span className="text-gray-400">Client GSTIN:</span>{" "}
                      <strong className="font-mono text-gray-800">{uploadRequest.client_gstin}</strong>
                    </div>
                  ) : null}
                </div>

                <div className="pt-2 border-t border-gray-200/70">
                  <p className="font-medium text-gray-700 mb-2">Uploaded Files:</p>
                  <ul className="space-y-1.5">
                    {doneFiles.map((item) => (
                      <li
                        key={item.id}
                        className="flex items-center justify-between text-gray-700 bg-white p-2 rounded border border-gray-200/60"
                      >
                        <span className="truncate font-medium pr-2">{item.file.name}</span>
                        <span className="font-mono text-gray-400 shrink-0">
                          {formatFileSize(item.file.size)}
                        </span>
                      </li>
                    ))}
                  </ul>
                </div>
              </div>

              <div className="rounded-xl border border-emerald-200 bg-emerald-50/70 p-3.5 text-xs text-emerald-900 flex items-center gap-2.5">
                <span className="text-base">✓</span>
                <p>
                  Your CA has been notified of this submission. You can safely close this window.
                </p>
              </div>
            </div>
          )}

          {(pageState === "ready" || pageState === "uploading" || pageState === "partial_failure") &&
            uploadRequest && (
              <div className="space-y-5">
                {/* Client Entity & Validity Banner */}
                {(uploadRequest.client_name || uploadRequest.client_gstin || expiryLabel) && (
                  <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-3 rounded-xl border border-gray-100 bg-[#FBFBFC] p-4 text-xs">
                    <div>
                      <p className="font-medium uppercase tracking-wider text-[10px] text-gray-400">
                        Requested for Client Entity
                      </p>
                      <p className="mt-0.5 text-sm font-semibold text-gray-900">
                        {uploadRequest.client_name || "Client Business"}
                      </p>
                      {uploadRequest.client_gstin ? (
                        <p className="mt-1 font-mono text-xs font-medium text-gray-600">
                          GSTIN: <span className="text-gray-900 font-semibold">{uploadRequest.client_gstin}</span>
                        </p>
                      ) : null}
                    </div>
                    {expiryLabel ? (
                      <div className="sm:text-right shrink-0">
                        <span className="inline-flex items-center gap-1 rounded-full bg-amber-50 px-2.5 py-1 text-[11px] font-medium text-amber-800 border border-amber-200/60">
                          Valid until {expiryLabel}
                        </span>
                      </div>
                    ) : null}
                  </div>
                )}

                {/* Request Details */}
                <div>
                  <h1 className="text-xl font-bold tracking-tight text-[var(--ink)]">
                    {uploadRequest.title}
                  </h1>
                  {uploadRequest.description && (
                    <p className="mt-1.5 text-sm leading-relaxed text-gray-600">
                      {uploadRequest.description}
                    </p>
                  )}
                </div>

                {/* File Dropzone */}
                {pageState === "ready" && (
                  <>
                    <div
                      className={`flex cursor-pointer flex-col items-center justify-center rounded-2xl border-2 border-dashed p-8 transition-all ${
                        isDragOver
                          ? "border-[var(--ink)] bg-gray-50 scale-[0.99]"
                          : "border-gray-300 hover:border-gray-400 bg-white"
                      }`}
                      onDragEnter={(e) => {
                        e.preventDefault();
                        e.stopPropagation();
                        dragCounter.current += 1;
                        if (e.dataTransfer.items && e.dataTransfer.items.length > 0) {
                          setIsDragOver(true);
                        }
                      }}
                      onDragLeave={(e) => {
                        e.preventDefault();
                        e.stopPropagation();
                        dragCounter.current -= 1;
                        if (dragCounter.current <= 0) {
                          dragCounter.current = 0;
                          setIsDragOver(false);
                        }
                      }}
                      onDragOver={(e) => {
                        e.preventDefault();
                        e.stopPropagation();
                      }}
                      onDrop={(e) => {
                        e.preventDefault();
                        e.stopPropagation();
                        dragCounter.current = 0;
                        setIsDragOver(false);
                        if (e.dataTransfer.files.length > 0) {
                          addFiles(e.dataTransfer.files);
                        }
                      }}
                      onClick={() => fileInputRef.current?.click()}
                      role="button"
                      tabIndex={0}
                      onKeyDown={(event) => {
                        if (event.key === "Enter" || event.key === " ") {
                          event.preventDefault();
                          fileInputRef.current?.click();
                        }
                      }}
                    >
                      <div className="flex h-12 w-12 items-center justify-center rounded-2xl bg-gray-100 text-gray-600">
                        <svg
                          className="h-6 w-6"
                          viewBox="0 0 24 24"
                          fill="none"
                          stroke="currentColor"
                          aria-hidden
                        >
                          <path
                            strokeLinecap="round"
                            strokeLinejoin="round"
                            strokeWidth="1.75"
                            d="M12 16V4m0 0l-4 4m4-4l4 4M4 20h16"
                          />
                        </svg>
                      </div>
                      <p className="mt-3 text-sm font-semibold text-[var(--ink)]">
                        Click to select or drag and drop files
                      </p>
                      <p className="mt-1 text-xs text-gray-500">
                        Supports <span className="font-medium text-gray-700">.xlsx, .csv, .pdf, .zip</span> up to 25 MB each
                      </p>
                      <input
                        ref={fileInputRef}
                        type="file"
                        multiple
                        accept=".xlsx,.csv,.pdf,.zip"
                        className="hidden"
                        onChange={(event) => {
                          if (event.target.files) {
                            addFiles(event.target.files);
                            event.target.value = "";
                          }
                        }}
                      />
                    </div>

                    {dropError && (
                      <div className="rounded-xl border border-red-200 bg-red-50 p-3 text-xs text-red-700">
                        {dropError}
                      </div>
                    )}
                  </>
                )}

                {/* File Queue & Live Progress */}
                {fileQueue.length > 0 && (
                  <div className="space-y-3 pt-2">
                    <div className="flex items-center justify-between text-xs font-semibold uppercase tracking-wider text-gray-400">
                      <span>Selected Documents ({fileQueue.length})</span>
                      {pendingCount > 0 && (
                        <span>{pendingCount} ready to upload</span>
                      )}
                    </div>
                    <ul className="divide-y divide-gray-100 rounded-xl border border-gray-200 overflow-hidden bg-white shadow-sm">
                      {fileQueue.map((item) => (
                        <li key={item.id} className="p-3.5 space-y-2">
                          <div className="flex items-center justify-between gap-3 text-sm">
                            <div className="min-w-0 flex-1">
                              <p className="truncate font-semibold text-gray-900">
                                {item.file.name}
                              </p>
                              <p className="text-xs text-gray-500">
                                {formatFileSize(item.file.size)}
                                {item.error ? (
                                  <span className="ml-2 font-medium text-red-600">
                                    — {item.error}
                                  </span>
                                ) : null}
                              </p>
                            </div>

                            <div className="flex items-center gap-2 shrink-0">
                              {item.status === "uploading" && (
                                <span className="font-mono text-xs font-semibold text-indigo-600">
                                  {item.progress}%
                                </span>
                              )}
                              {item.status === "done" && (
                                <span className="flex items-center gap-1 text-xs font-semibold text-emerald-600">
                                  <CheckIcon className="h-4 w-4" />
                                  Uploaded
                                </span>
                              )}
                              {item.status === "failed" && (
                                <span className="text-xs font-semibold text-red-600">
                                  Failed
                                </span>
                              )}
                              {item.status === "pending" && pageState === "ready" && (
                                <button
                                  type="button"
                                  onClick={() => removeFile(item.id)}
                                  className="rounded p-1 text-gray-400 hover:bg-gray-100 hover:text-gray-700 transition-colors"
                                  aria-label={`Remove ${item.file.name}`}
                                >
                                  <XIcon className="h-4 w-4" />
                                </button>
                              )}
                              {item.status === "failed" && pageState === "partial_failure" && (
                                <button
                                  type="button"
                                  onClick={() => handleRetry(item.id)}
                                  className="rounded-full border border-red-300 bg-white px-2.5 py-1 text-xs font-semibold text-red-700 hover:bg-red-50"
                                >
                                  Retry
                                </button>
                              )}
                            </div>
                          </div>

                          {/* Animated Progress Bar */}
                          {item.status === "uploading" && (
                            <div className="h-1.5 w-full overflow-hidden rounded-full bg-gray-100">
                              <div
                                className="h-full bg-[var(--ink)] transition-all duration-200"
                                style={{ width: `${item.progress}%` }}
                              />
                            </div>
                          )}
                        </li>
                      ))}
                    </ul>
                  </div>
                )}

                {/* Upload Action Button */}
                {pageState === "ready" && pendingCount > 0 && (
                  <div className="pt-2 flex justify-end">
                    <button
                      type="button"
                      onClick={handleUploadAll}
                      className="rounded-full bg-[var(--ink)] px-6 py-2.5 text-sm font-semibold text-white shadow-sm hover:opacity-90 transition-opacity"
                    >
                      Upload {pendingCount} {pendingCount === 1 ? "Document" : "Documents"} →
                    </button>
                  </div>
                )}

                {pageState === "partial_failure" && (
                  <p className="text-xs text-amber-800 bg-amber-50 p-3 rounded-xl border border-amber-200">
                    Some documents could not be uploaded. You can retry individual files above.
                  </p>
                )}
              </div>
            )}
        </div>

        {/* Security & Compliance Footer */}
        <div className="mt-8 text-center text-xs text-gray-400 space-y-1">
          <p>Files are end-to-end encrypted and transmitted directly to {firmName}.</p>
          <p className="text-[11px] text-gray-400/80">Secured with 256-bit encryption · Powered by ReconDesk</p>
        </div>
      </div>
    </div>
  );
}
