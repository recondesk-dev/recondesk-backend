"use client";

import { Download, Trash2 } from "lucide-react";
import { useCallback, useState } from "react";
import useSWR from "swr";

import { Modal } from "@/components/ui/Modal";
import { EmptyStateIllustration } from "@/components/ui/EmptyStateIllustration";
import { useToast } from "@/components/providers/ToastProvider";
import {
  isApiError,
  manageDataApi,
  type ManageDataFileInfo,
  type ManageDataFileType,
  type ManageDataRow,
} from "@/lib/api";
import {
  AUTH_PROFILE_SWR_OPTIONS,
  authProfileFetcher,
  normalizeAuthRole,
} from "@/lib/auth-profile";
import { useAccessToken } from "@/lib/hooks/useAccessToken";

const MANAGE_DATA_KEY = "manage-data-list";

function formatFileSize(bytes: number | null | undefined): string {
  if (bytes == null || bytes <= 0) return "—";
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

function formatDate(iso: string | null | undefined): string {
  if (!iso) return "—";
  return new Intl.DateTimeFormat("en-GB", {
    day: "numeric",
    month: "short",
    year: "numeric",
  }).format(new Date(iso));
}

function runStatusBadge(raw: string): { label: string; className: string } {
  const u = (raw || "").trim().toUpperCase();
  if (u === "FAILED") {
    return { label: "Failed", className: "bg-red-100 text-red-800" };
  }
  if (u === "COMPLETED" || u === "FINAL") {
    return { label: "Matched", className: "bg-green-100 text-green-800" };
  }
  return { label: "Processing", className: "bg-yellow-100 text-yellow-800" };
}

function FileCell({
  file,
  fileLabel,
  onDownload,
  onDelete,
  busy,
}: {
  file: ManageDataFileInfo;
  fileLabel: string;
  onDownload: () => void;
  onDelete: () => void;
  busy: boolean;
}) {
  if (file.is_deleted) {
    return (
      <span className="inline-flex rounded-full bg-gray-100 px-2.5 py-1 text-xs font-medium text-gray-500">
        Deleted
      </span>
    );
  }

  if (!file.name) {
    return <span className="text-[var(--text-secondary)]">—</span>;
  }

  return (
    <div className="flex items-start justify-between gap-2">
      <div className="min-w-0">
        <p className="truncate font-medium text-[var(--text-primary)]" title={file.name}>
          {file.name}
        </p>
        <p className="mt-0.5 text-xs text-[var(--text-secondary)]">
          {formatFileSize(file.size)}
        </p>
      </div>
      <div className="flex shrink-0 items-center gap-1">
        <button
          type="button"
          disabled={busy}
          onClick={onDownload}
          className="rounded-lg p-2 text-gray-400 transition-colors hover:bg-gray-100 hover:text-brand disabled:opacity-50"
          aria-label={`Download ${fileLabel}`}
          title={`Download ${fileLabel}`}
        >
          <Download size={16} />
        </button>
        <button
          type="button"
          disabled={busy}
          onClick={onDelete}
          className="rounded-lg p-2 text-gray-400 transition-colors hover:bg-gray-100 hover:text-gray-600 disabled:opacity-50"
          aria-label={`Delete ${fileLabel}`}
          title={`Delete ${fileLabel}`}
        >
          <Trash2 size={16} />
        </button>
      </div>
    </div>
  );
}

type PendingDelete = {
  runId: string;
  fileType: ManageDataFileType;
  fileName: string;
};

function ManageDataSkeleton() {
  return (
    <div className="overflow-hidden rounded-xl border border-[var(--border)] bg-[var(--surface)]">
      <div className="animate-pulse space-y-0">
        {[1, 2, 3].map((i) => (
          <div
            key={i}
            className="flex gap-4 border-b border-gray-100 px-4 py-4 last:border-b-0"
          >
            <div className="h-4 w-36 rounded bg-[var(--border)]" />
            <div className="h-4 w-20 rounded bg-[var(--border)]" />
            <div className="h-4 w-24 rounded bg-[var(--border)]" />
            <div className="h-4 w-40 rounded bg-[var(--border)]" />
            <div className="h-4 w-40 rounded bg-[var(--border)]" />
            <div className="h-4 w-24 rounded bg-[var(--border)]" />
          </div>
        ))}
      </div>
    </div>
  );
}

export function ManageDataPageContent() {
  const toast = useToast();
  const tokenState = useAccessToken();
  const authToken =
    typeof tokenState === "string" && tokenState.length > 0 ? tokenState : null;

  const meKey = authToken ? (["manage-data-me", authToken] as const) : null;
  const { data: me, isLoading: meLoading } = useSWR(
    meKey,
    ([, t]) => authProfileFetcher(t),
    AUTH_PROFILE_SWR_OPTIONS
  );

  const roleNorm = normalizeAuthRole(me?.role);
  const isAdmin = roleNorm === "admin";

  const listKey = authToken && isAdmin ? ([MANAGE_DATA_KEY, authToken] as const) : null;
  const {
    data: rows,
    error: listError,
    isLoading: listLoading,
    mutate: mutateList,
  } = useSWR(listKey, ([, t]) => manageDataApi.list(t), { keepPreviousData: true });

  const [pendingDelete, setPendingDelete] = useState<PendingDelete | null>(null);
  const [actionBusy, setActionBusy] = useState(false);

  const resolving = tokenState === null || (!!authToken && meKey !== null && meLoading);
  const showSkeleton =
    resolving || (!!authToken && isAdmin && listLoading && !rows);

  const handleDownload = useCallback(
    async (runId: string, fileType: ManageDataFileType) => {
      if (!authToken) return;
      setActionBusy(true);
      try {
        const { download_url } = await manageDataApi.downloadUrl(
          authToken,
          runId,
          fileType
        );
        window.open(download_url, "_blank", "noopener,noreferrer");
      } catch (e: unknown) {
        toast(isApiError(e) ? e.detail : "Download failed", "error");
      } finally {
        setActionBusy(false);
      }
    },
    [authToken, toast]
  );

  const confirmDelete = useCallback(async () => {
    if (!authToken || !pendingDelete) return;
    setActionBusy(true);
    try {
      await manageDataApi.deleteFile(
        authToken,
        pendingDelete.runId,
        pendingDelete.fileType
      );
      toast("File removed from storage", "success");
      setPendingDelete(null);
      await mutateList();
    } catch (e: unknown) {
      toast(isApiError(e) ? e.detail : "Delete failed", "error");
    } finally {
      setActionBusy(false);
    }
  }, [authToken, pendingDelete, mutateList, toast]);

  const totalRows = rows?.length ?? 0;

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-xl font-semibold text-[var(--text-primary)]">Manage Data</h1>
        <p className="mt-1 text-sm text-[var(--text-secondary)]">
          View, download, or remove stored GSTR-2B and Purchase Register files. Reconciliation
          results are kept when you delete a file.
        </p>
      </div>

      {resolving ? (
        <ManageDataSkeleton />
      ) : !isAdmin ? (
        <div className="rounded-xl border border-amber-200 bg-amber-50 px-5 py-4 text-sm text-amber-900">
          Only workspace admins can manage stored import files.
        </div>
      ) : !authToken ? (
        <div className="rounded-lg border border-amber-200 bg-amber-50 px-4 py-3 text-sm text-amber-950">
          Sign in to manage stored files.
        </div>
      ) : (
        <>
          <div className="flex items-center gap-2">
            <h2 className="text-lg font-semibold text-[var(--text-primary)]">Stored files</h2>
            {!showSkeleton && !listError && (
              <span className="rounded-full bg-[#F3F4F6] px-2 py-1 text-xs font-medium text-[var(--text-secondary)]">
                {totalRows}
              </span>
            )}
          </div>

          {listError && (
            <div className="rounded-lg border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-800">
              Could not load stored files.{" "}
              <button
                type="button"
                className="font-semibold text-brand underline"
                onClick={() => void mutateList()}
              >
                Retry
              </button>
            </div>
          )}

          {showSkeleton ? (
            <ManageDataSkeleton />
          ) : rows && rows.length === 0 ? (
            <div className="flex min-h-[320px] flex-col items-center justify-center rounded-xl border border-[var(--border)] bg-[var(--surface)] px-6 py-16 text-center">
              <div className="mx-auto w-full max-w-[400px]">
                <EmptyStateIllustration className="mx-auto text-gray-400" />
                <h3 className="mt-4 text-lg font-semibold text-gray-900">
                  No stored files yet
                </h3>
                <p className="mt-1 text-sm text-gray-500">
                  Files appear here after you run a reconciliation import.
                </p>
              </div>
            </div>
          ) : (
            <div className="overflow-hidden rounded-xl border border-[var(--border)] bg-[var(--surface)]">
              <div className="overflow-x-auto">
                <table className="min-w-[1020px] w-full border-collapse text-left text-sm">
                  <thead>
                    <tr className="border-b border-[var(--border)] bg-[#FAFAFB] text-xs font-semibold uppercase tracking-wide text-[var(--text-secondary)]">
                      <th className="px-4 py-3">Client</th>
                      <th className="px-4 py-3">Period</th>
                      <th className="px-4 py-3">Status</th>
                      <th className="px-4 py-3">GSTR-2B file</th>
                      <th className="px-4 py-3">Purchase Register file</th>
                      <th className="px-4 py-3">Uploaded date</th>
                    </tr>
                  </thead>
                  <tbody>
                    {(rows ?? []).map((row: ManageDataRow) => {
                      const status = runStatusBadge(row.status);
                      const uploadedAt =
                        row.gstr2b.uploaded_at ||
                        row.pr.uploaded_at ||
                        row.created_at;

                      return (
                        <tr
                          key={row.run_id}
                          className="border-b border-gray-100 hover:bg-gray-50 last:border-b-0"
                        >
                          <td className="px-4 py-3">
                            <div className="font-medium text-[var(--text-primary)]">
                              {row.client_name}
                            </div>
                            <div className="mt-0.5 font-mono text-xs text-[var(--text-secondary)]">
                              {row.gstin || "—"}
                            </div>
                          </td>
                          <td className="px-4 py-3 text-[var(--text-secondary)]">
                            {row.period ?? "—"}
                          </td>
                          <td className="px-4 py-3">
                            <span
                              className={`inline-flex rounded-full px-2 py-1 text-xs font-medium ${status.className}`}
                            >
                              {status.label}
                            </span>
                          </td>
                          <td className="px-4 py-3">
                            <FileCell
                              file={row.gstr2b}
                              fileLabel="GSTR-2B"
                              busy={actionBusy}
                              onDownload={() =>
                                void handleDownload(row.run_id, "gstr2b")
                              }
                              onDelete={() =>
                                setPendingDelete({
                                  runId: row.run_id,
                                  fileType: "gstr2b",
                                  fileName: row.gstr2b.name ?? "GSTR-2B file",
                                })
                              }
                            />
                          </td>
                          <td className="px-4 py-3">
                            <FileCell
                              file={row.pr}
                              fileLabel="Purchase Register"
                              busy={actionBusy}
                              onDownload={() => void handleDownload(row.run_id, "pr")}
                              onDelete={() =>
                                setPendingDelete({
                                  runId: row.run_id,
                                  fileType: "pr",
                                  fileName: row.pr.name ?? "Purchase Register file",
                                })
                              }
                            />
                          </td>
                          <td className="px-4 py-3 text-[var(--text-secondary)]">
                            {formatDate(uploadedAt)}
                          </td>
                        </tr>
                      );
                    })}
                  </tbody>
                </table>
              </div>
            </div>
          )}
        </>
      )}

      <Modal
        open={pendingDelete != null}
        onClose={() => !actionBusy && setPendingDelete(null)}
        title="Remove stored file?"
        footer={
          <>
            <button
              type="button"
              disabled={actionBusy}
              onClick={() => setPendingDelete(null)}
              className="rounded-full border border-[var(--border)] px-4 py-2 text-sm font-medium text-[var(--text-primary)] hover:bg-gray-50 disabled:opacity-50"
            >
              Cancel
            </button>
            <button
              type="button"
              disabled={actionBusy}
              onClick={() => void confirmDelete()}
              className="rounded-full bg-brand px-4 py-2 text-sm font-semibold text-white hover:bg-brand-hover disabled:opacity-50"
            >
              {actionBusy ? "Removing…" : "Remove file"}
            </button>
          </>
        }
      >
        <p className="text-sm text-[var(--text-secondary)]">
          This removes the stored file{" "}
          <span className="font-medium text-[var(--text-primary)]">
            {pendingDelete?.fileName}
          </span>
          . Reconciliation results for this run stay intact.
        </p>
      </Modal>
    </div>
  );
}
