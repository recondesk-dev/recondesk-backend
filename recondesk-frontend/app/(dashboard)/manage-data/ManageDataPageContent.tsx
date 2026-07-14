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

/** Same truthy check as manage_data delete endpoint on *_deleted_at columns. */
function isManageDataFileDeleted(file: ManageDataFileInfo): boolean {
  return Boolean(file.deleted_at);
}

function runStatusBadge(raw: string): { label: string; className: string } {
  const u = (raw || "").trim().toUpperCase();
  if (u === "FAILED") {
    return { label: "Failed", className: "bg-[#FEF2F2] text-[#EF4444]" };
  }
  if (u === "COMPLETED" || u === "FINAL") {
    return { label: "Matched", className: "bg-[var(--ink)] text-white" };
  }
  return { label: "Processing", className: "bg-[#F0F0F0] text-[#4B5563]" };
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
  if (isManageDataFileDeleted(file)) {
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
        <p className="truncate font-medium text-[var(--ink)]" title={file.name}>
          {file.name}
        </p>
        <p className="mt-0.5 text-xs text-gray-400">
          {formatFileSize(file.size)}
        </p>
      </div>
      <div className="flex shrink-0 items-center gap-1">
        <button
          type="button"
          disabled={busy}
          onClick={onDownload}
          className="rounded-full p-2 text-gray-400 transition-colors hover:bg-white hover:text-[var(--ink)] disabled:opacity-50"
          aria-label={`Download ${fileLabel}`}
          title={`Download ${fileLabel}`}
        >
          <Download size={16} />
        </button>
        <button
          type="button"
          disabled={busy}
          onClick={onDelete}
          className="rounded-full p-2 text-gray-400 transition-colors hover:bg-white hover:text-gray-700 disabled:opacity-50"
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
    <div className="overflow-hidden rounded-[1.25rem] ring-1 ring-[#F0F0F0]">
      <div className="animate-pulse space-y-0">
        {[1, 2, 3].map((i) => (
          <div
            key={i}
            className="flex gap-4 border-b border-[#F0F0F0] px-5 py-4 last:border-b-0"
          >
            <div className="h-4 w-36 rounded bg-gray-100" />
            <div className="h-4 w-20 rounded bg-gray-100" />
            <div className="h-4 w-24 rounded bg-gray-100" />
            <div className="h-4 w-40 rounded bg-gray-100" />
            <div className="h-4 w-40 rounded bg-gray-100" />
            <div className="h-4 w-24 rounded bg-gray-100" />
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
    async (
      runId: string,
      fileType: ManageDataFileType,
      file: ManageDataFileInfo
    ) => {
      if (!authToken || isManageDataFileDeleted(file)) return;
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
      const deletedRunId = pendingDelete.runId;
      const deletedFileType = pendingDelete.fileType;
      setPendingDelete(null);
      const deletedAt = new Date().toISOString();
      await mutateList(
        (current) =>
          current?.map((row) => {
            if (row.run_id !== deletedRunId) return row;
            const fileKey = deletedFileType === "gstr2b" ? "gstr2b" : "pr";
            return {
              ...row,
              [fileKey]: {
                ...row[fileKey],
                deleted_at: deletedAt,
                is_deleted: true,
              },
            };
          }),
        { revalidate: true }
      );
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
        <h1 className="text-2xl font-semibold tracking-tight text-[var(--ink)]">
          Manage Data
        </h1>
        <p className="mt-1 text-sm text-gray-500">
          View, download, or remove stored GSTR-2B and Purchase Register files.
          Reconciliation results are kept when you delete a file.
        </p>
      </div>

      {resolving ? (
        <section className="dashboard-card p-6">
          <ManageDataSkeleton />
        </section>
      ) : !isAdmin ? (
        <div className="rounded-[1.25rem] bg-amber-50 px-5 py-4 text-sm text-amber-900">
          Only workspace admins can manage stored import files.
        </div>
      ) : !authToken ? (
        <div className="rounded-[1.25rem] bg-amber-50 px-5 py-4 text-sm text-amber-950">
          Sign in to manage stored files.
        </div>
      ) : (
        <section className="dashboard-card space-y-5 p-6">
          <div className="flex items-center gap-2.5">
            <h2 className="text-lg font-semibold tracking-tight text-[var(--ink)]">
              Stored files
            </h2>
            {!showSkeleton && !listError && (
              <span className="rounded-full bg-[#F0F0F0] px-2.5 py-1 text-xs font-semibold text-gray-600">
                {totalRows}
              </span>
            )}
          </div>

          {listError && (
            <div className="rounded-[1.25rem] bg-red-50 px-5 py-4 text-sm text-red-800">
              Could not load stored files.{" "}
              <button
                type="button"
                className="font-semibold text-[var(--ink)] underline"
                onClick={() => void mutateList()}
              >
                Retry
              </button>
            </div>
          )}

          {showSkeleton ? (
            <ManageDataSkeleton />
          ) : rows && rows.length === 0 ? (
            <div className="flex min-h-[280px] flex-col items-center justify-center rounded-[1.25rem] bg-[#F7F7F8] px-6 py-16 text-center">
              <div className="mx-auto w-full max-w-[400px]">
                <EmptyStateIllustration className="mx-auto text-gray-300" />
                <h3 className="mt-4 text-lg font-semibold text-[var(--ink)]">
                  No stored files yet
                </h3>
                <p className="mt-1 text-sm text-gray-500">
                  Files appear here after you run a reconciliation import.
                </p>
              </div>
            </div>
          ) : (
            <div className="overflow-hidden rounded-[1.25rem] ring-1 ring-[#F0F0F0]">
              <div className="overflow-x-auto">
                <table className="min-w-[1020px] w-full border-collapse text-left text-sm">
                  <thead>
                    <tr className="border-b border-[#F0F0F0] text-[11px] font-medium uppercase tracking-widest text-gray-400">
                      <th className="px-5 py-4">Client</th>
                      <th className="px-4 py-4">Period</th>
                      <th className="px-4 py-4">Status</th>
                      <th className="px-4 py-4">GSTR-2B file</th>
                      <th className="px-4 py-4">Purchase Register file</th>
                      <th className="px-5 py-4">Uploaded date</th>
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
                          className="border-b border-[#F0F0F0] transition-colors hover:bg-[#F7F7F8] last:border-b-0"
                        >
                          <td className="px-5 py-3.5">
                            <div className="font-medium text-[var(--ink)]">
                              {row.client_name}
                            </div>
                            <div className="mt-0.5 font-mono text-xs text-gray-400">
                              {row.gstin || "—"}
                            </div>
                          </td>
                          <td className="px-4 py-3.5 text-gray-500">
                            {row.period ?? "—"}
                          </td>
                          <td className="px-4 py-3.5">
                            <span
                              className={`inline-flex rounded-full px-3 py-1 text-xs font-medium ${status.className}`}
                            >
                              {status.label}
                            </span>
                          </td>
                          <td className="px-4 py-3.5">
                            <FileCell
                              file={row.gstr2b}
                              fileLabel="GSTR-2B"
                              busy={actionBusy}
                              onDownload={() =>
                                void handleDownload(row.run_id, "gstr2b", row.gstr2b)
                              }
                              onDelete={() => {
                                if (isManageDataFileDeleted(row.gstr2b)) return;
                                setPendingDelete({
                                  runId: row.run_id,
                                  fileType: "gstr2b",
                                  fileName: row.gstr2b.name ?? "GSTR-2B file",
                                });
                              }}
                            />
                          </td>
                          <td className="px-4 py-3.5">
                            <FileCell
                              file={row.pr}
                              fileLabel="Purchase Register"
                              busy={actionBusy}
                              onDownload={() =>
                                void handleDownload(row.run_id, "pr", row.pr)
                              }
                              onDelete={() => {
                                if (isManageDataFileDeleted(row.pr)) return;
                                setPendingDelete({
                                  runId: row.run_id,
                                  fileType: "pr",
                                  fileName: row.pr.name ?? "Purchase Register file",
                                });
                              }}
                            />
                          </td>
                          <td className="px-5 py-3.5 text-gray-500">
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
        </section>
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
              className="rounded-full bg-[#F5F5F6] px-4 py-2 text-sm font-medium text-gray-700 transition-colors hover:bg-gray-200/70 disabled:opacity-50"
            >
              Cancel
            </button>
            <button
              type="button"
              disabled={actionBusy}
              onClick={() => void confirmDelete()}
              className="rounded-full bg-[var(--ink)] px-4 py-2 text-sm font-semibold text-white transition-opacity hover:opacity-90 disabled:opacity-50"
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
