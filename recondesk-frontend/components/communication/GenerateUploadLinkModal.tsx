"use client";

import { useEffect, useState } from "react";
import type { SupabaseClient } from "@supabase/supabase-js";
import { createClient } from "@/lib/supabase/client";

type UploadRequest = {
  id: string;
  client_id: string;
  organization_id: string;
  token: string;
  title: string;
  description: string | null;
  expires_at: string | null;
  created_by_user_id: string;
  created_at: string;
};

type CommunicationLog = {
  id: string;
  template_type: string;
  message_content: string;
  sent_via: string;
  client_id: string;
  organization_id: string;
  sent_by_user_id: string;
  created_at: string;
};

type ModalState = "idle" | "loading" | "error" | "success";

type UploadRequestInsert = Omit<UploadRequest, "id" | "created_at">;

type CommunicationLogInsert = Omit<CommunicationLog, "id" | "created_at">;

type GenerateUploadLinkModalProps = {
  clientId: string;
  organizationId: string;
  createdByUserId: string;
  isOpen: boolean;
  onClose: () => void;
  onSuccess: (uploadRequestId: string) => void;
};

function formatDateForInput(date: Date): string {
  const year = date.getFullYear();
  const month = String(date.getMonth() + 1).padStart(2, "0");
  const day = String(date.getDate()).padStart(2, "0");
  return `${year}-${month}-${day}`;
}

function defaultExpiryDate(): string {
  const date = new Date();
  date.setDate(date.getDate() + 7);
  return formatDateForInput(date);
}

function todayDateString(): string {
  return formatDateForInput(new Date());
}

function dateInputToIso(dateValue: string): string {
  const [year, month, day] = dateValue.split("-").map(Number);
  const date = new Date(year, month - 1, day, 23, 59, 59, 999);
  return date.toISOString();
}

function generateToken(): string {
  const array = new Uint8Array(32);
  crypto.getRandomValues(array);
  return Array.from(array)
    .map((b) => b.toString(16).padStart(2, "0"))
    .join("");
}

function getSupabaseClient(): SupabaseClient {
  return createClient() as SupabaseClient;
}

const inputClassName =
  "w-full rounded-full border-0 bg-[#F5F5F6] px-4 py-2.5 text-sm font-medium text-[var(--ink)] placeholder:text-gray-400 focus:outline-none focus:ring-2 focus:ring-black/10 disabled:cursor-not-allowed disabled:opacity-60";

export default function GenerateUploadLinkModal({
  clientId,
  organizationId,
  createdByUserId,
  isOpen,
  onClose,
  onSuccess,
}: GenerateUploadLinkModalProps) {
  const [modalState, setModalState] = useState<ModalState>("idle");
  const [title, setTitle] = useState("");
  const [description, setDescription] = useState("");
  const [expiryDate, setExpiryDate] = useState(defaultExpiryDate);
  const [errorMessage, setErrorMessage] = useState("");
  const [shareableUrl, setShareableUrl] = useState("");
  const [copied, setCopied] = useState(false);

  useEffect(() => {
    if (!isOpen) return;

    setModalState("idle");
    setTitle("");
    setDescription("");
    setExpiryDate(defaultExpiryDate());
    setErrorMessage("");
    setShareableUrl("");
    setCopied(false);
  }, [isOpen]);

  useEffect(() => {
    if (!copied) return;

    const timer = window.setTimeout(() => setCopied(false), 2000);
    return () => window.clearTimeout(timer);
  }, [copied]);

  if (!isOpen) return null;

  function resetToIdle(): void {
    setModalState("idle");
    setTitle("");
    setDescription("");
    setExpiryDate(defaultExpiryDate());
    setErrorMessage("");
    setShareableUrl("");
    setCopied(false);
  }

  async function handleSubmit(event: React.FormEvent<HTMLFormElement>): Promise<void> {
    event.preventDefault();

    const trimmedTitle = title.trim();
    if (!trimmedTitle) {
      setErrorMessage("Request title is required.");
      setModalState("error");
      return;
    }

    setModalState("loading");
    setErrorMessage("");

    try {
      const token = generateToken();
      const expiresAt = expiryDate.trim() ? dateInputToIso(expiryDate) : null;

      let createdId: string | null = null;

      // 1. Primary: backend API (Aurora PRIMARY)
      try {
        const res = await fetch("/api/upload/request", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            client_id: clientId,
            organization_id: organizationId,
            token,
            title: trimmedTitle,
            description: description.trim() || null,
            expires_at: expiresAt,
          }),
        });
        if (res.ok) {
          const resData = await res.json();
          if (resData?.id) {
            createdId = String(resData.id);
          }
        }
      } catch (backendErr) {
        console.warn("Backend /api/upload/request call failed, falling back to Supabase", backendErr);
      }

      // 2. Supabase Fallback (temporary, non-blocking)
      if (!createdId) {
        const supabase = getSupabaseClient();
        const uploadInsert: UploadRequestInsert = {
          client_id: clientId,
          organization_id: organizationId,
          token,
          title: trimmedTitle,
          description: description.trim() || null,
          expires_at: expiresAt,
          created_by_user_id: createdByUserId,
        };

        const { data, error } = await supabase
          .from("upload_requests")
          .insert(uploadInsert)
          .select("id")
          .single();

        if (error) {
          throw new Error(error.message);
        }

        const created = data as { id: string } | null;
        if (!created?.id) {
          throw new Error("Upload request was created but no ID was returned.");
        }
        createdId = created.id;

        const logInsert: CommunicationLogInsert = {
          template_type: "upload_request",
          message_content: `Upload request created: ${trimmedTitle}`,
          sent_via: "upload_request",
          client_id: clientId,
          organization_id: organizationId,
          sent_by_user_id: createdByUserId,
        };

        const { error: logError } = await supabase.from("communication_logs").insert(logInsert);
        if (logError) {
          console.warn("Supabase communication log fallback insert failed:", logError.message);
        }
      }

      const url = `${window.location.origin}/upload/${token}`;
      setShareableUrl(url);
      setModalState("success");
      onSuccess(createdId);
    } catch (err: unknown) {
      const message = err instanceof Error ? err.message : "Something went wrong";
      setErrorMessage(message);
      setModalState("error");
    }
  }

  async function handleCopyLink(): Promise<void> {
    if (!shareableUrl) return;

    try {
      await navigator.clipboard.writeText(shareableUrl);
      setCopied(true);
    } catch (err: unknown) {
      const message = err instanceof Error ? err.message : "Failed to copy link";
      setErrorMessage(message);
      setModalState("error");
    }
  }

  const isLoading = modalState === "loading";
  const minDate = todayDateString();

  return (
    <div className="fixed inset-0 z-[100] flex items-center justify-center p-4">
      <button
        type="button"
        className="absolute inset-0 bg-black/40"
        aria-label="Close dialog"
        onClick={onClose}
        disabled={isLoading}
      />

      <div
        role="dialog"
        aria-modal="true"
        aria-label="Generate upload link"
        className="relative z-10 w-full max-w-md rounded-[1.5rem] bg-white shadow-[var(--shadow-lift)]"
      >
        <div className="flex items-start justify-between border-b border-[#F0F0F0] px-5 py-4">
          <div>
            <h2 className="text-base font-semibold tracking-tight text-[var(--ink)]">
              Generate Upload Link
            </h2>
            <p className="mt-1 text-sm text-gray-500">
              Create a secure link for your client to upload documents.
            </p>
          </div>
          <button
            type="button"
            onClick={onClose}
            disabled={isLoading}
            className="rounded-full p-1.5 text-gray-400 transition-colors hover:bg-[#F5F5F6] hover:text-[var(--ink)] disabled:cursor-not-allowed disabled:opacity-50"
            aria-label="Close"
          >
            <svg className="h-5 w-5" viewBox="0 0 24 24" fill="none" stroke="currentColor" aria-hidden>
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth="2" d="M6 18L18 6M6 6l12 12" />
            </svg>
          </button>
        </div>

        <div className="px-5 py-4">
          {modalState === "success" ? (
            <div className="space-y-4">
              <div className="rounded-[1.25rem] bg-emerald-50 px-4 py-3">
                <p className="text-sm font-medium text-emerald-800">
                  Upload link generated successfully
                </p>
                <p className="mt-1 text-sm text-emerald-700">
                  Share this link with your client. It can be used to upload files securely.
                </p>
              </div>

              <div>
                <label className="mb-1.5 block text-sm font-medium text-[var(--ink)]">
                  Shareable link
                </label>
                <div className="flex gap-2">
                  <input
                    type="text"
                    readOnly
                    value={shareableUrl}
                    className={`${inputClassName} font-mono text-xs`}
                  />
                  <button
                    type="button"
                    onClick={() => void handleCopyLink()}
                    className="shrink-0 rounded-full bg-[var(--ink)] px-4 py-2 text-sm font-semibold text-white transition-opacity hover:opacity-90"
                  >
                    {copied ? "Copied!" : "Copy Link"}
                  </button>
                </div>
              </div>

              <div className="flex justify-end gap-2 pt-2">
                <button
                  type="button"
                  onClick={onClose}
                  className="rounded-full bg-[#F5F5F6] px-4 py-2 text-sm font-semibold text-[var(--ink)] transition-colors hover:bg-gray-200/70"
                >
                  Done
                </button>
                <button
                  type="button"
                  onClick={resetToIdle}
                  className="rounded-full bg-[var(--ink)] px-4 py-2 text-sm font-semibold text-white transition-opacity hover:opacity-90"
                >
                  Generate Another
                </button>
              </div>
            </div>
          ) : (
            <form onSubmit={(event) => void handleSubmit(event)} className="space-y-4">
              <div>
                <label
                  htmlFor="upload-request-title"
                  className="mb-1.5 block text-sm font-medium text-[var(--ink)]"
                >
                  Request Title <span className="text-red-500">*</span>
                </label>
                <input
                  id="upload-request-title"
                  type="text"
                  required
                  value={title}
                  onChange={(event) => setTitle(event.target.value)}
                  disabled={isLoading}
                  placeholder="e.g. March 2026 GSTR-2B documents"
                  className={inputClassName}
                />
              </div>

              <div>
                <label
                  htmlFor="upload-request-description"
                  className="mb-1.5 block text-sm font-medium text-[var(--ink)]"
                >
                  Description
                </label>
                <textarea
                  id="upload-request-description"
                  value={description}
                  onChange={(event) => setDescription(event.target.value)}
                  disabled={isLoading}
                  maxLength={300}
                  rows={3}
                  placeholder="Optional instructions for your client"
                  className="w-full resize-none rounded-2xl border-0 bg-[#F5F5F6] px-4 py-2.5 text-sm font-medium text-[var(--ink)] placeholder:text-gray-400 focus:outline-none focus:ring-2 focus:ring-black/10 disabled:cursor-not-allowed disabled:opacity-60"
                />
                <p className="mt-1 text-xs text-gray-400">
                  {description.length}/300 characters
                </p>
              </div>

              <div>
                <label
                  htmlFor="upload-request-expiry"
                  className="mb-1.5 block text-sm font-medium text-[var(--ink)]"
                >
                  Expiry Date
                </label>
                <input
                  id="upload-request-expiry"
                  type="date"
                  value={expiryDate}
                  min={minDate}
                  onChange={(event) => setExpiryDate(event.target.value)}
                  disabled={isLoading}
                  className={inputClassName}
                />
              </div>

              {modalState === "error" && errorMessage && (
                <p className="rounded-[1.25rem] bg-red-50 px-4 py-3 text-sm text-red-800">
                  {errorMessage}
                </p>
              )}

              <div className="flex justify-end gap-2 pt-2">
                <button
                  type="button"
                  onClick={onClose}
                  disabled={isLoading}
                  className="rounded-full bg-[#F5F5F6] px-4 py-2 text-sm font-semibold text-[var(--ink)] transition-colors hover:bg-gray-200/70 disabled:cursor-not-allowed disabled:opacity-50"
                >
                  Cancel
                </button>
                <button
                  type="submit"
                  disabled={isLoading}
                  className="inline-flex items-center justify-center gap-2 rounded-full bg-[var(--ink)] px-4 py-2 text-sm font-semibold text-white transition-opacity hover:opacity-90 disabled:cursor-not-allowed disabled:opacity-50"
                >
                  {isLoading && (
                    <svg
                      className="h-4 w-4 animate-spin"
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
                  )}
                  Generate Link
                </button>
              </div>
            </form>
          )}
        </div>
      </div>
    </div>
  );
}
