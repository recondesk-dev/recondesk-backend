"use client";

import { Loader2, X } from "lucide-react";
import { useCallback, useEffect, useRef, useState } from "react";
import {
  buildFollowupLetterDraft,
  buildFollowupLetterPdfBlob,
  buildInvoiceSnapshot,
  defaultSupplierDisplayName,
  followupPdfFilename,
  templateTypeForRowCount,
  type FollowupInvoiceSnapshotItem,
  type RiskRowForFollowup,
} from "@/lib/supplierFollowupLetter";
import { downloadBlobAsFile } from "@/lib/download";
import { apiFetch, isApiError } from "@/lib/api";

const DISCLAIMER_MODAL =
  "This is a system-generated follow-up draft. Please review before sending. This letter is generated for informational and communication purposes. It does not constitute legal advice.";

export function SupplierFollowupLetterModal({
  open,
  onClose,
  runId,
  taxPeriod,
  clientName,
  clientGstin,
  rows,
  token,
}: {
  open: boolean;
  onClose: () => void;
  runId: string;
  taxPeriod: string;
  clientName: string;
  clientGstin: string;
  rows: RiskRowForFollowup[];
  token: string;
}) {
  const snapshotRef = useRef<FollowupInvoiceSnapshotItem[]>([]);
  const loggedGeneratedKeyRef = useRef<string | null>(null);

  const [supplierName, setSupplierName] = useState("");
  const [body, setBody] = useState("");
  const [auditBusy, setAuditBusy] = useState(false);
  const [auditWarning, setAuditWarning] = useState<string | null>(null);
  const [auditError, setAuditError] = useState<string | null>(null);
  const [copyOk, setCopyOk] = useState(false);

  const supplierGstin = (rows[0]?.supplier_gstin?.trim() ?? "").toUpperCase();

  const postAudit = useCallback(
    async (
      status: "generated" | "downloaded" | "copied"
    ): Promise<boolean> => {
      const snap = snapshotRef.current;
      if (!snap.length || !token) return false;
      setAuditBusy(true);
      if (status !== "generated") setAuditError(null);
      try {
        const display = defaultSupplierDisplayName(rows, supplierName);
        await apiFetch<{ id: string; status: string; generated_at: string }>(
          `/api/reconcile/runs/${encodeURIComponent(runId)}/supplier-followup/audit`,
          {
            method: "POST",
            token,
            body: JSON.stringify({
              supplier_gstin: supplierGstin,
              record_ids: snap.map((s) => s.record_id),
              tax_period: taxPeriod,
              invoice_snapshot: snap,
              template_type: templateTypeForRowCount(snap.length),
              status,
              supplier_name_display: display,
            }),
          }
        );
        if (status === "generated") setAuditWarning(null);
        return true;
      } catch (e) {
        const msg = isApiError(e)
          ? e.detail
          : e instanceof Error
            ? e.message
            : "Could not save audit record";
        if (status === "generated") {
          setAuditWarning(
            `${msg} You can still copy or download the letter.`
          );
        } else {
          setAuditError(msg);
        }
        return false;
      } finally {
        setAuditBusy(false);
      }
    },
    [runId, token, taxPeriod, supplierGstin, supplierName, rows]
  );

  useEffect(() => {
    if (!open || rows.length === 0) return;
    const snap = buildInvoiceSnapshot(rows);
    snapshotRef.current = snap;
    setAuditWarning(null);
    setAuditError(null);
    setCopyOk(false);

    setSupplierName(
      rows.map((r) => r.trade_name?.trim()).find(Boolean) || ""
    );
    setBody(
      buildFollowupLetterDraft({
        clientName,
        clientGstin,
        taxPeriod,
        supplierDisplayName: defaultSupplierDisplayName(rows, ""),
        supplierGstin,
        snapshot: snap,
      })
    );

    const genKey = snap
      .map((s) => s.record_id)
      .sort()
      .join("|");
    if (loggedGeneratedKeyRef.current !== genKey) {
      loggedGeneratedKeyRef.current = genKey;
      void postAudit("generated");
    }
  }, [
    open,
    rows,
    clientName,
    clientGstin,
    taxPeriod,
    supplierGstin,
    postAudit,
  ]);

  useEffect(() => {
    if (!open) loggedGeneratedKeyRef.current = null;
  }, [open]);

  const refreshBodyFromName = useCallback(() => {
    const snap = snapshotRef.current;
    if (!snap.length) return;
    setBody(
      buildFollowupLetterDraft({
        clientName,
        clientGstin,
        taxPeriod,
        supplierDisplayName: defaultSupplierDisplayName(rows, supplierName),
        supplierGstin,
        snapshot: snap,
      })
    );
  }, [clientName, clientGstin, taxPeriod, supplierGstin, supplierName, rows]);

  const handleCopy = async () => {
    try {
      await navigator.clipboard.writeText(body);
      setCopyOk(true);
      window.setTimeout(() => setCopyOk(false), 2000);
      void postAudit("copied");
    } catch {
      setAuditError("Clipboard unavailable");
    }
  };

  const handleDownloadPdf = async () => {
    setAuditError(null);
    try {
      const blob = await buildFollowupLetterPdfBlob(body, DISCLAIMER_MODAL);
      downloadBlobAsFile(blob, followupPdfFilename(supplierGstin, taxPeriod));
      void postAudit("downloaded");
    } catch {
      setAuditError("Could not generate PDF. Please try again or use Copy message.");
    }
  };

  if (!open) return null;

  return (
    <div
      className="fixed inset-0 z-[100] flex items-center justify-center bg-black/40 p-4"
      role="dialog"
      aria-modal="true"
      aria-labelledby="followup-letter-title"
    >
      <div className="flex max-h-[90vh] w-full max-w-2xl flex-col overflow-hidden rounded-2xl border border-[#F0F0F0] bg-white shadow-xl">
        <div className="flex items-center justify-between border-b border-[#F0F0F0] px-5 py-4">
          <h2
            id="followup-letter-title"
            className="text-lg font-semibold text-gray-900"
          >
            Supplier follow-up letter
          </h2>
          <button
            type="button"
            onClick={onClose}
            className="rounded-lg p-1 text-gray-500 hover:bg-gray-100"
            aria-label="Close"
          >
            <X className="h-5 w-5" />
          </button>
        </div>

        <div className="min-h-0 flex-1 overflow-y-auto px-5 py-4 space-y-4">
          <div className="grid gap-3 text-[13px] sm:grid-cols-2">
            <div>
              <p className="text-[11px] font-medium uppercase tracking-wide text-gray-400">
                Client
              </p>
              <p className="font-medium text-gray-900">{clientName}</p>
              <p className="font-mono text-gray-500">{clientGstin || "—"}</p>
            </div>
            <div>
              <p className="text-[11px] font-medium uppercase tracking-wide text-gray-400">
                Tax period
              </p>
              <p className="font-medium text-gray-900">{taxPeriod}</p>
            </div>
            <div className="sm:col-span-2">
              <label className="text-[11px] font-medium uppercase tracking-wide text-gray-400">
                Supplier name
              </label>
              <input
                type="text"
                value={supplierName}
                onChange={(e) => setSupplierName(e.target.value)}
                onBlur={refreshBodyFromName}
                placeholder={supplierGstin ? `M/s ${supplierGstin}` : "Supplier name"}
                className="mt-1 w-full rounded-xl border border-[#E5E7EB] px-3 py-2 text-[13px] outline-none focus:border-brand focus:ring-2 focus:ring-brand/20"
              />
              <p className="mt-1 font-mono text-[12px] text-gray-500">
                GSTIN: {supplierGstin}
              </p>
            </div>
          </div>

          <p className="text-[12px] text-gray-500">{DISCLAIMER_MODAL}</p>

          <div>
            <label className="mb-1 block text-[11px] font-medium uppercase tracking-wide text-gray-400">
              Letter (editable)
            </label>
            <textarea
              value={body}
              onChange={(e) => setBody(e.target.value)}
              rows={16}
              className="w-full resize-y rounded-xl border border-[#E5E7EB] px-3 py-2 font-mono text-[12px] leading-relaxed text-gray-800 outline-none focus:border-brand focus:ring-2 focus:ring-brand/20"
            />
          </div>

          {auditWarning && (
            <p className="text-[13px] text-amber-800">{auditWarning}</p>
          )}
          {auditError && (
            <p className="text-[13px] text-red-600">{auditError}</p>
          )}
        </div>

        <div className="flex flex-wrap items-center justify-end gap-2 border-t border-[#F0F0F0] px-5 py-4">
          {auditBusy && (
            <span className="mr-auto inline-flex items-center gap-1 text-[12px] text-gray-500">
              <Loader2 className="h-3 w-3 animate-spin" />
              Saving…
            </span>
          )}
          <button
            type="button"
            onClick={onClose}
            className="rounded-xl border border-[#E5E7EB] bg-white px-4 py-2 text-[13px] font-medium text-gray-700 hover:bg-gray-50"
          >
            Close
          </button>
          <button
            type="button"
            onClick={() => void handleCopy()}
            className="rounded-xl border border-[#E5E7EB] bg-white px-4 py-2 text-[13px] font-medium text-gray-700 hover:bg-gray-50"
          >
            {copyOk ? "Copied!" : "Copy message"}
          </button>
          <button
            type="button"
            onClick={() => void handleDownloadPdf()}
            className="rounded-xl bg-brand px-4 py-2 text-[13px] font-semibold text-white hover:bg-brand-hover"
          >
            Download PDF
          </button>
        </div>
      </div>
    </div>
  );
}
