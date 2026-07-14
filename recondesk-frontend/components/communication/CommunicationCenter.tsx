"use client";

import { useCallback, useEffect, useState } from "react";
import type { SupabaseClient } from "@supabase/supabase-js";
import GenerateUploadLinkModal from "@/components/communication/GenerateUploadLinkModal";
import { createClient } from "@/lib/supabase/client";

type UploadRequest = {
  id: string;
  token: string;
  title: string;
  description: string | null;
  expires_at: string | null;
  created_at: string;
};

type CommunicationLog = {
  id: string;
  template_type: string;
  message_content: string;
  sent_via: string;
  sent_by_user_id: string;
  notes: string | null;
  created_at: string;
  user_profiles: { full_name: string } | null;
};

type UploadedFile = {
  id: string;
  filename: string;
  file_size: number;
  mime_type: string;
  public_url: string;
  uploaded_at: string;
  upload_requests: { title: string } | null;
};

type CommunicationCenterProps = {
  clientId: string;
  organizationId: string;
  userId: string;
};

const UPLOAD_PAGE_SIZE = 10;
const LOG_PAGE_SIZE = 20;
const UPLOADED_FILES_PAGE_SIZE = 20;

function getSupabaseClient(): SupabaseClient {
  return createClient() as SupabaseClient;
}

function formatDate(dateStr: string): string {
  return new Intl.DateTimeFormat("en-GB", {
    day: "numeric",
    month: "short",
    year: "numeric",
  }).format(new Date(dateStr));
}

function formatDateTime(dateStr: string): string {
  return new Intl.DateTimeFormat("en-GB", {
    day: "numeric",
    month: "short",
    year: "numeric",
    hour: "numeric",
    minute: "2-digit",
    hour12: true,
  }).format(new Date(dateStr));
}

function formatFileSize(bytes: number): string {
  if (bytes < 1024 * 1024) {
    return `${(bytes / 1024).toFixed(1)} KB`;
  }
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

function simplifyMimeType(mimeType: string): string {
  if (mimeType === "application/pdf") return "PDF";
  if (mimeType === "text/csv") return "CSV";
  if (mimeType === "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet") {
    return "Excel";
  }
  if (mimeType === "application/zip" || mimeType === "application/x-zip-compressed") {
    return "ZIP";
  }
  return mimeType;
}

function isExpired(expiresAt: string | null): boolean {
  if (!expiresAt) return false;
  return new Date(expiresAt) < new Date();
}

function formatTemplateType(templateType: string): string {
  if (templateType === "upload_request") return "Upload Request";
  if (templateType === "missing_invoices") return "Missing Invoices";
  return templateType
    .split("_")
    .map((word) => word.charAt(0).toUpperCase() + word.slice(1))
    .join(" ");
}

function formatSentVia(sentVia: string): string {
  if (!sentVia) return "—";
  return sentVia.charAt(0).toUpperCase() + sentVia.slice(1);
}

function truncateNotes(value: string | null, fallback: string): string {
  const text = (value ?? fallback).trim();
  if (text.length <= 60) return text;
  return `${text.slice(0, 60)}…`;
}

function TableSkeleton({ rows = 3 }: { rows?: number }) {
  return (
    <div className="space-y-2">
      {Array.from({ length: rows }).map((_, index) => (
        <div key={index} className="h-10 animate-pulse rounded-2xl bg-gray-100" />
      ))}
    </div>
  );
}

function EmptyState({ message }: { message: string }) {
  return (
    <div className="flex flex-col items-center justify-center rounded-2xl bg-[#F7F7F8] px-4 py-12 text-center">
      <svg
        className="mb-3 h-10 w-10 text-gray-300"
        viewBox="0 0 24 24"
        fill="none"
        stroke="currentColor"
        aria-hidden
      >
        <path
          strokeLinecap="round"
          strokeLinejoin="round"
          strokeWidth="1.5"
          d="M13.828 10.172a4 4 0 00-5.656 0l-4 4a4 4 0 105.656 5.656l1.102-1.101m-.758-4.899a4 4 0 005.656 0l4-4a4 4 0 00-5.656-5.656l-1.1 1.1"
        />
      </svg>
      <p className="text-sm text-gray-400">{message}</p>
    </div>
  );
}

const loadMoreBtnClass =
  "rounded-full bg-[#F5F5F6] px-4 py-2 text-sm font-semibold text-[var(--ink)] transition-colors hover:bg-gray-200/70 disabled:cursor-not-allowed disabled:opacity-40";

const tableHeadRow =
  "border-b border-[#F0F0F0] text-[11px] font-medium uppercase tracking-widest text-gray-400";

const tableRowClass =
  "border-b border-[#F0F0F0] transition-colors last:border-b-0 hover:bg-[#F7F7F8]";

export default function CommunicationCenter({
  clientId,
  organizationId,
  userId,
}: CommunicationCenterProps) {
  const [modalOpen, setModalOpen] = useState(false);
  const [successBanner, setSuccessBanner] = useState(false);
  const [uploadRequests, setUploadRequests] = useState<UploadRequest[]>([]);
  const [uploadedFiles, setUploadedFiles] = useState<UploadedFile[]>([]);
  const [communicationLogs, setCommunicationLogs] = useState<CommunicationLog[]>([]);
  const [uploadsLoading, setUploadsLoading] = useState(true);
  const [filesLoading, setFilesLoading] = useState(true);
  const [logsLoading, setLogsLoading] = useState(true);
  const [uploadsLoadingMore, setUploadsLoadingMore] = useState(false);
  const [filesLoadingMore, setFilesLoadingMore] = useState(false);
  const [logsLoadingMore, setLogsLoadingMore] = useState(false);
  const [hasMoreUploads, setHasMoreUploads] = useState(false);
  const [hasMoreFiles, setHasMoreFiles] = useState(false);
  const [hasMoreLogs, setHasMoreLogs] = useState(false);
  const [uploadsError, setUploadsError] = useState<string | null>(null);
  const [filesError, setFilesError] = useState<string | null>(null);
  const [logsError, setLogsError] = useState<string | null>(null);
  const [copiedRequestId, setCopiedRequestId] = useState<string | null>(null);

  const fetchUploadRequests = useCallback(
    async (offset: number, append: boolean) => {
      if (append) {
        setUploadsLoadingMore(true);
      } else {
        setUploadsLoading(true);
      }
      setUploadsError(null);

      try {
        const supabase = getSupabaseClient();
        const { data, error } = await supabase
          .from("upload_requests")
          .select("id, token, title, description, expires_at, created_at")
          .eq("client_id", clientId)
          .order("created_at", { ascending: false })
          .range(offset, offset + UPLOAD_PAGE_SIZE - 1);

        if (error) {
          throw new Error(error.message);
        }

        const rows = (data ?? []) as UploadRequest[];
        setUploadRequests((prev) => (append ? [...prev, ...rows] : rows));
        setHasMoreUploads(rows.length === UPLOAD_PAGE_SIZE);
      } catch (err: unknown) {
        const message = err instanceof Error ? err.message : "Failed to load upload requests";
        setUploadsError(message);
      } finally {
        setUploadsLoading(false);
        setUploadsLoadingMore(false);
      }
    },
    [clientId]
  );

  const fetchUploadedFiles = useCallback(
    async (offset: number, append: boolean, uploadRequestIds: string[]) => {
      if (uploadRequestIds.length === 0) {
        setUploadedFiles([]);
        setHasMoreFiles(false);
        setFilesLoading(false);
        setFilesLoadingMore(false);
        return;
      }

      if (append) {
        setFilesLoadingMore(true);
      } else {
        setFilesLoading(true);
      }
      setFilesError(null);

      try {
        const supabase = getSupabaseClient();
        const { data, error } = await supabase
          .from("uploaded_files")
          .select(
            "id, filename, file_size, mime_type, public_url, uploaded_at, upload_requests(title)"
          )
          .in("upload_request_id", uploadRequestIds)
          .order("uploaded_at", { ascending: false })
          .range(offset, offset + UPLOADED_FILES_PAGE_SIZE - 1);

        if (error) {
          throw new Error(error.message);
        }

        const rows = (data ?? []) as unknown as UploadedFile[];
        setUploadedFiles((prev) => (append ? [...prev, ...rows] : rows));
        setHasMoreFiles(rows.length === UPLOADED_FILES_PAGE_SIZE);
      } catch (err: unknown) {
        const message = err instanceof Error ? err.message : "Failed to load uploaded files";
        setFilesError(message);
      } finally {
        setFilesLoading(false);
        setFilesLoadingMore(false);
      }
    },
    []
  );

  const fetchCommunicationLogs = useCallback(
    async (offset: number, append: boolean) => {
      if (append) {
        setLogsLoadingMore(true);
      } else {
        setLogsLoading(true);
      }
      setLogsError(null);

      try {
        const supabase = getSupabaseClient();
        const { data, error } = await supabase
          .from("communication_logs")
          .select(
            "id, template_type, message_content, sent_via, sent_by_user_id, notes, created_at, user_profiles(full_name)"
          )
          .eq("client_id", clientId)
          .order("created_at", { ascending: false })
          .range(offset, offset + LOG_PAGE_SIZE - 1);

        if (error) {
          throw new Error(error.message);
        }

        const rows = (data ?? []) as unknown as CommunicationLog[];
        setCommunicationLogs((prev) => (append ? [...prev, ...rows] : rows));
        setHasMoreLogs(rows.length === LOG_PAGE_SIZE);
      } catch (err: unknown) {
        const message = err instanceof Error ? err.message : "Failed to load communication log";
        setLogsError(message);
      } finally {
        setLogsLoading(false);
        setLogsLoadingMore(false);
      }
    },
    [clientId]
  );

  useEffect(() => {
    void fetchUploadRequests(0, false);
    void fetchCommunicationLogs(0, false);
  }, [fetchUploadRequests, fetchCommunicationLogs]);

  useEffect(() => {
    if (uploadsLoading) return;

    const uploadRequestIds = uploadRequests.map((request) => request.id);
    void fetchUploadedFiles(0, false, uploadRequestIds);
  }, [uploadRequests, uploadsLoading, fetchUploadedFiles]);

  useEffect(() => {
    if (!copiedRequestId) return;

    const timer = window.setTimeout(() => setCopiedRequestId(null), 2000);
    return () => window.clearTimeout(timer);
  }, [copiedRequestId]);

  useEffect(() => {
    if (!successBanner) return;

    const timer = window.setTimeout(() => setSuccessBanner(false), 3000);
    return () => window.clearTimeout(timer);
  }, [successBanner]);

  async function handleUploadSuccess(uploadRequestId: string): Promise<void> {
    setModalOpen(false);
    setSuccessBanner(true);

    try {
      const supabase = getSupabaseClient();
      const { data, error } = await supabase
        .from("upload_requests")
        .select("id, token, title, description, expires_at, created_at")
        .eq("id", uploadRequestId)
        .single();

      if (error) {
        throw new Error(error.message);
      }

      const row = data as UploadRequest | null;
      if (row) {
        setUploadRequests((prev) => {
          const exists = prev.some((item) => item.id === row.id);
          if (exists) return prev;
          return [row, ...prev];
        });
      }
    } catch (err: unknown) {
      const message = err instanceof Error ? err.message : "Failed to refresh upload request";
      setUploadsError(message);
    }
  }

  async function handleCopyLink(request: UploadRequest): Promise<void> {
    try {
      const url = `${window.location.origin}/upload/${request.token}`;
      await navigator.clipboard.writeText(url);
      setCopiedRequestId(request.id);
    } catch (err: unknown) {
      const message = err instanceof Error ? err.message : "Failed to copy link";
      setUploadsError(message);
    }
  }

  const uploadRequestIds = uploadRequests.map((request) => request.id);

  return (
    <div className="space-y-6">
      {successBanner && (
        <div className="rounded-[1.25rem] bg-emerald-50 px-5 py-4 text-sm text-emerald-800">
          Upload link generated and logged.
        </div>
      )}

      <div className="flex flex-wrap items-start justify-between gap-4">
        <div>
          <h1 className="text-lg font-semibold tracking-tight text-[var(--ink)]">
            Communication Center
          </h1>
          <p className="mt-1 text-sm text-gray-500">
            Manage upload requests and client follow-ups.
          </p>
        </div>
        <button
          type="button"
          onClick={() => setModalOpen(true)}
          className="rounded-full bg-[var(--ink)] px-4 py-2 text-sm font-semibold text-white transition-opacity hover:opacity-90"
        >
          Generate Upload Link
        </button>
      </div>

      <section className="dashboard-card space-y-4 p-6">
        <h2 className="text-base font-semibold tracking-tight text-[var(--ink)]">
          Upload Requests
        </h2>

        {uploadsError && (
          <div className="rounded-[1.25rem] bg-red-50 px-5 py-3 text-sm text-red-800">
            {uploadsError}
          </div>
        )}

        {uploadsLoading ? (
          <TableSkeleton />
        ) : uploadRequests.length === 0 ? (
          <EmptyState message="No upload links generated yet." />
        ) : (
          <>
            <div className="overflow-hidden rounded-[1.25rem] ring-1 ring-[#F0F0F0]">
              <div className="overflow-x-auto">
                <table className="min-w-full border-collapse text-left text-sm">
                  <thead>
                    <tr className={tableHeadRow}>
                      {["Title", "Created", "Expires", "Status", "Link"].map((heading) => (
                        <th key={heading} className="px-5 py-4">
                          {heading}
                        </th>
                      ))}
                    </tr>
                  </thead>
                  <tbody>
                    {uploadRequests.map((request) => {
                      const expired = isExpired(request.expires_at);
                      return (
                        <tr key={request.id} className={tableRowClass}>
                          <td className="px-5 py-3.5 font-medium text-[var(--ink)]">
                            {request.title}
                          </td>
                          <td className="px-4 py-3.5 text-gray-500">
                            {formatDate(request.created_at)}
                          </td>
                          <td className="px-4 py-3.5 text-gray-500">
                            {request.expires_at ? formatDate(request.expires_at) : "No expiry"}
                          </td>
                          <td className="px-4 py-3.5">
                            <span
                              className={
                                expired
                                  ? "inline-flex rounded-full bg-red-50 px-2.5 py-0.5 text-xs font-semibold text-red-700"
                                  : "inline-flex rounded-full bg-emerald-50 px-2.5 py-0.5 text-xs font-semibold text-emerald-700"
                              }
                            >
                              {expired ? "Expired" : "Active"}
                            </span>
                          </td>
                          <td className="px-5 py-3.5">
                            <button
                              type="button"
                              onClick={() => void handleCopyLink(request)}
                              className="rounded-full bg-[#F5F5F6] px-3 py-1.5 text-xs font-semibold text-[var(--ink)] transition-colors hover:bg-gray-200/70"
                            >
                              {copiedRequestId === request.id ? "Copied!" : "Copy"}
                            </button>
                          </td>
                        </tr>
                      );
                    })}
                  </tbody>
                </table>
              </div>
            </div>

            {hasMoreUploads && (
              <div className="flex justify-center">
                <button
                  type="button"
                  disabled={uploadsLoadingMore}
                  onClick={() => void fetchUploadRequests(uploadRequests.length, true)}
                  className={loadMoreBtnClass}
                >
                  {uploadsLoadingMore ? "Loading…" : "Load more"}
                </button>
              </div>
            )}
          </>
        )}
      </section>

      <section className="dashboard-card space-y-4 p-6">
        <h2 className="text-base font-semibold tracking-tight text-[var(--ink)]">
          Uploaded Files
        </h2>

        {filesError && (
          <div className="rounded-[1.25rem] bg-red-50 px-5 py-3 text-sm text-red-800">
            {filesError}
          </div>
        )}

        {uploadsLoading || filesLoading ? (
          <TableSkeleton rows={3} />
        ) : uploadRequests.length === 0 || uploadedFiles.length === 0 ? (
          <EmptyState message="No files uploaded yet." />
        ) : (
          <>
            <div className="overflow-hidden rounded-[1.25rem] ring-1 ring-[#F0F0F0]">
              <div className="overflow-x-auto">
                <table className="min-w-full border-collapse text-left text-sm">
                  <thead>
                    <tr className={tableHeadRow}>
                      {[
                        "File Name",
                        "Size",
                        "Type",
                        "Upload Request",
                        "Uploaded At",
                        "Download",
                      ].map((heading) => (
                        <th key={heading} className="px-5 py-4">
                          {heading}
                        </th>
                      ))}
                    </tr>
                  </thead>
                  <tbody>
                    {uploadedFiles.map((file) => (
                      <tr key={file.id} className={tableRowClass}>
                        <td className="px-5 py-3.5 font-medium text-[var(--ink)]">
                          {file.filename}
                        </td>
                        <td className="px-4 py-3.5 text-gray-500">
                          {formatFileSize(file.file_size)}
                        </td>
                        <td className="px-4 py-3.5 text-gray-500">
                          {simplifyMimeType(file.mime_type)}
                        </td>
                        <td className="px-4 py-3.5 text-[var(--ink)]">
                          {file.upload_requests?.title ?? "—"}
                        </td>
                        <td className="px-4 py-3.5 text-gray-500">
                          {formatDateTime(file.uploaded_at)}
                        </td>
                        <td className="px-5 py-3.5">
                          <a
                            href={file.public_url}
                            target="_blank"
                            rel="noopener noreferrer"
                            className="font-semibold text-[var(--ink)] underline"
                          >
                            Download
                          </a>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </div>

            {hasMoreFiles && (
              <div className="flex justify-center">
                <button
                  type="button"
                  disabled={filesLoadingMore}
                  onClick={() =>
                    void fetchUploadedFiles(uploadedFiles.length, true, uploadRequestIds)
                  }
                  className={loadMoreBtnClass}
                >
                  {filesLoadingMore ? "Loading…" : "Load more"}
                </button>
              </div>
            )}
          </>
        )}
      </section>

      <section className="dashboard-card space-y-4 p-6">
        <h2 className="text-base font-semibold tracking-tight text-[var(--ink)]">
          Communication Log
        </h2>

        {logsError && (
          <div className="rounded-[1.25rem] bg-red-50 px-5 py-3 text-sm text-red-800">
            {logsError}
          </div>
        )}

        {logsLoading ? (
          <TableSkeleton />
        ) : communicationLogs.length === 0 ? (
          <EmptyState message="No communication logged yet." />
        ) : (
          <>
            <div className="overflow-hidden rounded-[1.25rem] ring-1 ring-[#F0F0F0]">
              <div className="overflow-x-auto">
                <table className="min-w-full border-collapse text-left text-sm">
                  <thead>
                    <tr className={tableHeadRow}>
                      {["Date", "Type", "Sent Via", "Staff", "Notes"].map((heading) => (
                        <th key={heading} className="px-5 py-4">
                          {heading}
                        </th>
                      ))}
                    </tr>
                  </thead>
                  <tbody>
                    {communicationLogs.map((log) => (
                      <tr key={log.id} className={tableRowClass}>
                        <td className="px-5 py-3.5 text-gray-500">
                          {formatDateTime(log.created_at)}
                        </td>
                        <td className="px-4 py-3.5 font-medium text-[var(--ink)]">
                          {formatTemplateType(log.template_type)}
                        </td>
                        <td className="px-4 py-3.5 text-gray-500">
                          {formatSentVia(log.sent_via)}
                        </td>
                        <td className="px-4 py-3.5 text-[var(--ink)]">
                          {log.user_profiles?.full_name?.trim() || "—"}
                        </td>
                        <td className="max-w-xs px-5 py-3.5 text-gray-500">
                          {truncateNotes(log.notes, log.message_content)}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </div>

            {hasMoreLogs && (
              <div className="flex justify-center">
                <button
                  type="button"
                  disabled={logsLoadingMore}
                  onClick={() => void fetchCommunicationLogs(communicationLogs.length, true)}
                  className={loadMoreBtnClass}
                >
                  {logsLoadingMore ? "Loading…" : "Load more"}
                </button>
              </div>
            )}
          </>
        )}
      </section>

      <GenerateUploadLinkModal
        clientId={clientId}
        organizationId={organizationId}
        createdByUserId={userId}
        isOpen={modalOpen}
        onClose={() => setModalOpen(false)}
        onSuccess={(uploadRequestId) => void handleUploadSuccess(uploadRequestId)}
      />
    </div>
  );
}
