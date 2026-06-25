"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import type { SupabaseClient } from "@supabase/supabase-js";
import { createClient } from "@/lib/supabase/client";
import { Logo } from "@/components/ui/Logo";

type UploadRequest = {
  id: string;
  title: string;
  description: string | null;
  expires_at: string | null;
};

type FileStatus = "pending" | "uploading" | "done" | "failed";

type UploadedFile = {
  file: File;
  status: FileStatus;
  error: string | null;
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
const MAX_FILE_SIZE = 26214400;

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
      <div className="h-7 w-40 rounded bg-gray-200 dark:bg-gray-800" />
      <div className="h-4 w-full rounded bg-gray-200 dark:bg-gray-800" />
      <div className="h-4 w-3/4 rounded bg-gray-200 dark:bg-gray-800" />
      <div className="h-32 w-full rounded-xl bg-gray-200 dark:bg-gray-800" />
    </div>
  );
}

export default function UploadPageClient({ token }: { token: string }) {
  const [pageState, setPageState] = useState<PageState>("validating");
  const [uploadRequest, setUploadRequest] = useState<UploadRequest | null>(null);
  const [fileQueue, setFileQueue] = useState<FileQueueItem[]>([]);
  const [dropError, setDropError] = useState<string | null>(null);
  const [isDragOver, setIsDragOver] = useState(false);
  const fileInputRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    let cancelled = false;

    async function validateToken(): Promise<void> {
      try {
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

  async function uploadFileItem(
    uploadRequestId: string,
    item: FileQueueItem
  ): Promise<{ ok: boolean; error: string | null }> {
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

      const putRes = await fetch(presignData.upload_url, {
        method: "PUT",
        headers: { "Content-Type": contentType },
        body: item.file,
      });

      if (!putRes.ok) {
        throw new Error(`Upload failed (${putRes.status})`);
      }

      const supabase = getSupabaseClient();
      const fileInsert: UploadedFileInsert = {
        upload_request_id: uploadRequestId,
        filename: item.file.name,
        file_size: item.file.size,
        mime_type: contentType,
        public_url: presignData.public_url,
      };
      const { error: insertError } = await supabase.from("uploaded_files").insert(fileInsert);

      if (insertError) {
        throw new Error(insertError.message);
      }

      return { ok: true, error: null };
    } catch (err: unknown) {
      const message = err instanceof Error ? err.message : "Upload failed";
      return { ok: false, error: message };
    }
  }

  async function runUploads(items: FileQueueItem[]): Promise<void> {
    if (!uploadRequest || items.length === 0) return;

    const itemIds = new Set(items.map((item) => item.id));

    setPageState("uploading");
    setDropError(null);
    setFileQueue((prev) =>
      prev.map((entry) =>
        itemIds.has(entry.id)
          ? { ...entry, status: "uploading", error: null }
          : entry
      )
    );

    const results = await Promise.allSettled(
      items.map(async (item) => {
        const result = await uploadFileItem(uploadRequest.id, item);
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
          return { ...entry, status: "done" as const, error: null };
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

  return (
    <div className="recondesk-textured-bg min-h-screen">
      <div className="mx-auto max-w-lg px-4 py-16">
        <Logo width={210} height={40} />
        {/* TODO: Replace with organization logo and name */}

        <div className="mt-8 rounded-xl border border-gray-200 bg-white p-8 dark:border-gray-800 dark:bg-gray-900">
          {pageState === "validating" && <ValidatingSkeleton />}

          {pageState === "invalid" && (
            <div className="text-center">
              <div className="mx-auto flex h-12 w-12 items-center justify-center rounded-full bg-red-100 dark:bg-red-950/40">
                <XIcon className="h-6 w-6 text-red-600 dark:text-red-400" />
              </div>
              <h1 className="mt-4 text-lg font-semibold text-gray-900 dark:text-gray-100">
                Invalid link
              </h1>
              <p className="mt-2 text-sm text-gray-600 dark:text-gray-400">
                This link is invalid or does not exist.
              </p>
            </div>
          )}

          {pageState === "expired" && (
            <div className="text-center">
              <div className="mx-auto flex h-12 w-12 items-center justify-center rounded-full bg-amber-100 dark:bg-amber-950/40">
                <XIcon className="h-6 w-6 text-amber-600 dark:text-amber-400" />
              </div>
              <h1 className="mt-4 text-lg font-semibold text-gray-900 dark:text-gray-100">
                Link expired
              </h1>
              <p className="mt-2 text-sm text-gray-600 dark:text-gray-400">
                This upload link has expired.
              </p>
            </div>
          )}

          {pageState === "success" && (
            <div>
              <div className="flex items-center gap-3">
                <div className="flex h-10 w-10 items-center justify-center rounded-full bg-green-100 dark:bg-green-950/40">
                  <CheckIcon className="h-5 w-5 text-green-600 dark:text-green-400" />
                </div>
                <h1 className="text-lg font-semibold text-gray-900 dark:text-gray-100">
                  Documents uploaded successfully.
                </h1>
              </div>
              <ul className="mt-6 space-y-2">
                {doneFiles.map((item) => (
                  <li
                    key={item.id}
                    className="flex items-center gap-2 text-sm text-gray-700 dark:text-gray-300"
                  >
                    <CheckIcon className="h-4 w-4 shrink-0 text-green-600 dark:text-green-400" />
                    <span className="truncate">{item.file.name}</span>
                  </li>
                ))}
              </ul>
            </div>
          )}

          {(pageState === "ready" || pageState === "uploading" || pageState === "partial_failure") &&
            uploadRequest && (
              <div>
                <h1 className="text-lg font-semibold text-gray-900 dark:text-gray-100">
                  {uploadRequest.title}
                </h1>
                {uploadRequest.description && (
                  <p className="mt-2 text-sm text-gray-600 dark:text-gray-400">
                    {uploadRequest.description}
                  </p>
                )}

                {pageState === "ready" && (
                  <>
                    <div
                      className={`mt-6 flex cursor-pointer flex-col items-center justify-center rounded-xl border-2 border-dashed px-6 py-10 transition-colors ${
                        isDragOver
                          ? "border-indigo-500 bg-indigo-50 dark:bg-indigo-950/20"
                          : "border-gray-300 dark:border-gray-700"
                      }`}
                      onDragOver={(event) => {
                        event.preventDefault();
                        setIsDragOver(true);
                      }}
                      onDragLeave={(event) => {
                        event.preventDefault();
                        setIsDragOver(false);
                      }}
                      onDrop={(event) => {
                        event.preventDefault();
                        setIsDragOver(false);
                        if (event.dataTransfer.files.length > 0) {
                          addFiles(event.dataTransfer.files);
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
                      <svg
                        className="h-10 w-10 text-gray-400"
                        viewBox="0 0 24 24"
                        fill="none"
                        stroke="currentColor"
                        aria-hidden
                      >
                        <path
                          strokeLinecap="round"
                          strokeLinejoin="round"
                          strokeWidth="1.5"
                          d="M12 16V4m0 0l-4 4m4-4l4 4M4 20h16"
                        />
                      </svg>
                      <p className="mt-3 text-sm font-medium text-gray-700 dark:text-gray-300">
                        Drag and drop files here
                      </p>
                      <p className="mt-1 text-xs text-gray-500 dark:text-gray-400">
                        .xlsx, .csv, .pdf, .zip — up to 25 MB each
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
                      <p className="mt-3 text-sm text-red-600 dark:text-red-400">{dropError}</p>
                    )}
                  </>
                )}

                {fileQueue.length > 0 && (
                  <div className="mt-6">
                    <h2 className="text-sm font-medium text-gray-700 dark:text-gray-300">
                      Files
                    </h2>
                    <ul className="mt-3 divide-y divide-gray-200 rounded-lg border border-gray-200 dark:divide-gray-800 dark:border-gray-800">
                      {fileQueue.map((item) => (
                        <li
                          key={item.id}
                          className="flex items-center gap-3 px-4 py-3 text-sm"
                        >
                          <div className="min-w-0 flex-1">
                            <p className="truncate font-medium text-gray-900 dark:text-gray-100">
                              {item.file.name}
                            </p>
                            <p className="text-xs text-gray-500 dark:text-gray-400">
                              {formatFileSize(item.file.size)}
                              {item.error ? (
                                <span className="ml-2 text-red-600 dark:text-red-400">
                                  — {item.error}
                                </span>
                              ) : null}
                            </p>
                          </div>

                          <span
                            className={`shrink-0 text-xs font-medium capitalize ${
                              item.status === "done"
                                ? "text-green-600 dark:text-green-400"
                                : item.status === "failed"
                                  ? "text-red-600 dark:text-red-400"
                                  : item.status === "uploading"
                                    ? "text-indigo-600 dark:text-indigo-400"
                                    : "text-gray-500 dark:text-gray-400"
                            }`}
                          >
                            {item.status === "uploading" ? (
                              <span className="inline-flex items-center gap-1">
                                <svg
                                  className="h-3 w-3 animate-spin"
                                  viewBox="0 0 24 24"
                                  fill="none"
                                  aria-hidden
                                >
                                  <circle
                                    className="opacity-25"
                                    cx="12"
                                    cy="12"
                                    r="10"
                                    stroke="currentColor"
                                    strokeWidth="4"
                                  />
                                  <path
                                    className="opacity-75"
                                    fill="currentColor"
                                    d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z"
                                  />
                                </svg>
                                Uploading
                              </span>
                            ) : (
                              item.status
                            )}
                          </span>

                          {item.status === "pending" && pageState === "ready" && (
                            <button
                              type="button"
                              onClick={() => removeFile(item.id)}
                              className="shrink-0 rounded p-1 text-gray-400 hover:bg-gray-100 hover:text-gray-600 dark:hover:bg-gray-800 dark:hover:text-gray-200"
                              aria-label={`Remove ${item.file.name}`}
                            >
                              <XIcon className="h-4 w-4" />
                            </button>
                          )}

                          {item.status === "done" && (
                            <CheckIcon className="h-4 w-4 shrink-0 text-green-600 dark:text-green-400" />
                          )}

                          {item.status === "failed" && pageState === "partial_failure" && (
                            <button
                              type="button"
                              onClick={() => handleRetry(item.id)}
                              className="shrink-0 rounded-lg border border-gray-200 px-2.5 py-1 text-xs font-medium text-gray-700 hover:bg-gray-50 dark:border-gray-700 dark:text-gray-300 dark:hover:bg-gray-800"
                            >
                              Retry
                            </button>
                          )}
                        </li>
                      ))}
                    </ul>
                  </div>
                )}

                {pageState === "ready" && pendingCount > 0 && (
                  <div className="mt-6 flex justify-end">
                    <button
                      type="button"
                      onClick={handleUploadAll}
                      className="rounded-full bg-indigo-600 px-4 py-2 text-sm font-medium text-white transition-colors hover:bg-indigo-700"
                    >
                      Upload {pendingCount} {pendingCount === 1 ? "file" : "files"}
                    </button>
                  </div>
                )}

                {pageState === "partial_failure" && (
                  <p className="mt-4 text-sm text-gray-600 dark:text-gray-400">
                    Some files could not be uploaded. Retry the failed files above.
                  </p>
                )}
              </div>
            )}
        </div>

        <p className="mt-6 text-center text-xs text-gray-500 dark:text-gray-400">
          Your files are transmitted securely and used only for GST reconciliation.
        </p>
      </div>
    </div>
  );
}
