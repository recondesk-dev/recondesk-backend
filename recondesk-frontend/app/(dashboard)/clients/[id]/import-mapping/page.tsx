"use client";

import { useCallback, useMemo, useState } from "react";
import { useParams } from "next/navigation";
import useSWR from "swr";

import {
  clientsApi,
  prUploadApi,
  type ApiError,
  type ClientImportMappingItem,
  type ImportTargetField,
} from "@/lib/api";
import { useAccessToken } from "@/lib/hooks/useAccessToken";
import { useToast } from "@/components/providers/ToastProvider";

const TARGET_FIELDS: ImportTargetField[] = [
  "gstin",
  "invoice_number",
  "invoice_date",
  "taxable_value",
  "cgst",
  "sgst",
  "igst",
  "cess",
];

const LABELS: Record<ImportTargetField, string> = {
  gstin: "GSTIN",
  invoice_number: "Invoice number",
  invoice_date: "Invoice date",
  taxable_value: "Taxable value",
  cgst: "CGST",
  sgst: "SGST",
  igst: "IGST",
  cess: "Cess",
};

const REQUIRED: ImportTargetField[] = [
  "gstin",
  "invoice_number",
  "invoice_date",
  "taxable_value",
];

const TAX: ImportTargetField[] = ["cgst", "sgst", "igst", "cess"];

function PanelSkeleton() {
  return (
    <div className="animate-pulse space-y-3 rounded-xl border border-[var(--border)] bg-[var(--surface)] p-6">
      <div className="h-4 w-48 rounded bg-[#E5E7EB]" />
      <div className="h-10 w-full rounded bg-[#E5E7EB]" />
      <div className="h-32 w-full rounded bg-[#E5E7EB]" />
    </div>
  );
}

export default function ClientImportMappingPage() {
  const params = useParams();
  const id = typeof params?.id === "string" ? params.id : "";
  const tokenState = useAccessToken();
  const authToken =
    typeof tokenState === "string" && tokenState.length > 0 ? tokenState : null;
  const toast = useToast();

  const clientKey = authToken && id ? (["client-import-map", authToken, id] as const) : null;
  const mappingKey =
    authToken && id ? (["pr-import-mapping", authToken, id] as const) : null;

  const { data: client, error: clientError, isLoading: clientLoading } = useSWR(
    clientKey,
    ([, token, cid]) => clientsApi.get(token, cid),
    { revalidateOnFocus: false }
  );

  const {
    data: mappingRes,
    error: mappingError,
    isLoading: mappingLoading,
    mutate,
  } = useSWR(
    mappingKey,
    ([, token, cid]) => prUploadApi.getMapping(token, cid),
    { revalidateOnFocus: false }
  );

  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState<Record<ImportTargetField, string>>(() =>
    Object.fromEntries(TARGET_FIELDS.map((f) => [f, ""])) as Record<
      ImportTargetField,
      string
    >
  );
  const [busy, setBusy] = useState(false);
  const [formError, setFormError] = useState<string | null>(null);

  const rows = mappingRes?.mappings ?? null;

  const startEdit = useCallback(() => {
    const next = Object.fromEntries(TARGET_FIELDS.map((f) => [f, ""])) as Record<
      ImportTargetField,
      string
    >;
    for (const r of rows ?? []) {
      next[r.target_field] = r.source_column_name;
    }
    setDraft(next);
    setFormError(null);
    setEditing(true);
  }, [rows]);

  const canSave = useMemo(() => {
    const mapped = TARGET_FIELDS.filter((f) => draft[f]?.trim());
    const hasRequired = REQUIRED.every((f) => draft[f]?.trim());
    const hasTax = TAX.some((f) => draft[f]?.trim());
    return hasRequired && hasTax && mapped.length > 0;
  }, [draft]);

  const onSave = async () => {
    if (!authToken || !id) return;
    setFormError(null);
    if (!canSave) {
      setFormError(
        "Map GSTIN, invoice number, invoice date, taxable value, and at least one tax field."
      );
      return;
    }
    const items: ClientImportMappingItem[] = TARGET_FIELDS.filter((f) =>
      draft[f]?.trim()
    ).map((f) => ({
      target_field: f,
      source_column_name: draft[f].trim(),
    }));
    setBusy(true);
    try {
      await prUploadApi.saveMapping(authToken, id, items);
      await mutate();
      setEditing(false);
      toast("Import mapping saved", "success");
    } catch (e) {
      const ae = e as ApiError;
      setFormError(ae.detail ?? "Could not save mapping.");
    } finally {
      setBusy(false);
    }
  };

  const onDelete = async () => {
    if (!authToken || !id) return;
    if (
      !window.confirm(
        "Delete saved import mapping? The next purchase-register upload will ask you to map columns again."
      )
    ) {
      return;
    }
    setBusy(true);
    try {
      await prUploadApi.deleteMapping(authToken, id);
      await mutate();
      setEditing(false);
      toast("Import mapping deleted", "success");
    } catch (e) {
      const ae = e as ApiError;
      toast(ae.detail ?? "Could not delete mapping.", "error");
    } finally {
      setBusy(false);
    }
  };

  if (!authToken || clientLoading || mappingLoading) {
    return <PanelSkeleton />;
  }

  if (clientError || !client) {
    return (
      <div className="rounded-lg border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-800">
        Could not load client.
      </div>
    );
  }

  return (
    <div className="space-y-4">
      <div>
        <h1 className="text-lg font-semibold text-[var(--text-primary)]">Import Mapping</h1>
        <p className="mt-1 text-sm text-[var(--text-secondary)]">
          Saved purchase-register column mapping for{" "}
          <strong>{client.trade_name || client.gstin}</strong>. Used automatically on the next
          upload when headers match.
        </p>
      </div>

      {mappingError ? (
        <div className="rounded-lg border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-800">
          Could not load saved mapping.
        </div>
      ) : null}

      <div className="rounded-xl border border-[var(--border)] bg-[var(--surface)] p-6">
        {!rows?.length && !editing ? (
          <div className="space-y-3">
            <p className="text-sm text-[var(--text-secondary)]">
              No saved mapping yet. Map columns during the next purchase-register upload, or add
              one here.
            </p>
            <button
              type="button"
              onClick={startEdit}
              className="rounded-full bg-brand px-4 py-2 text-sm font-medium text-white hover:bg-brand-hover"
            >
              Add mapping
            </button>
          </div>
        ) : null}

        {rows?.length && !editing ? (
          <div className="space-y-4">
            <table className="w-full border-collapse text-left text-sm">
              <thead>
                <tr className="border-b border-[var(--border)] text-[var(--text-secondary)]">
                  <th className="py-2 pr-3">Target field</th>
                  <th className="py-2 pr-3">Source column</th>
                </tr>
              </thead>
              <tbody>
                {rows.map((r) => (
                  <tr key={r.target_field} className="border-b border-[var(--border)]">
                    <td className="py-2 pr-3 font-medium">
                      {LABELS[r.target_field] ?? r.target_field}
                      {REQUIRED.includes(r.target_field) ? (
                        <span className="text-red-600">*</span>
                      ) : null}
                    </td>
                    <td className="py-2 pr-3 font-mono text-xs">{r.source_column_name}</td>
                  </tr>
                ))}
              </tbody>
            </table>
            <div className="flex gap-2">
              <button
                type="button"
                onClick={startEdit}
                disabled={busy}
                className="rounded-full border border-[var(--border)] px-4 py-2 text-sm font-medium"
              >
                Edit
              </button>
              <button
                type="button"
                onClick={() => void onDelete()}
                disabled={busy}
                className="rounded-full border border-red-200 px-4 py-2 text-sm font-medium text-red-700"
              >
                Delete
              </button>
            </div>
          </div>
        ) : null}

        {editing ? (
          <div className="space-y-4">
            <p className="text-sm text-[var(--text-secondary)]">
              Enter the exact column header from this client&apos;s purchase register for each
              field.
            </p>
            <div className="space-y-3">
              {TARGET_FIELDS.map((tf) => (
                <label key={tf} className="flex flex-col gap-1 text-sm sm:flex-row sm:items-center">
                  <span className="w-40 font-medium text-[var(--text-primary)]">
                    {LABELS[tf]}
                    {REQUIRED.includes(tf) || TAX.includes(tf) ? (
                      <span className="text-red-600">*</span>
                    ) : null}
                  </span>
                  <input
                    value={draft[tf]}
                    onChange={(e) =>
                      setDraft((prev) => ({ ...prev, [tf]: e.target.value }))
                    }
                    placeholder="Column header in file"
                    className="flex-1 rounded-lg border border-[var(--border)] bg-white px-3 py-2 text-sm"
                  />
                </label>
              ))}
            </div>
            <p className="text-xs text-[var(--text-secondary)]">
              * Required: GSTIN, invoice number, invoice date, taxable value, and at least one of
              CGST / SGST / IGST / Cess.
            </p>
            {formError ? (
              <div className="rounded-lg border border-red-200 bg-red-50 px-3 py-2 text-sm text-red-800">
                {formError}
              </div>
            ) : null}
            <div className="flex gap-2">
              <button
                type="button"
                disabled={busy || !canSave}
                onClick={() => void onSave()}
                className="rounded-full bg-brand px-4 py-2 text-sm font-medium text-white disabled:opacity-50 hover:bg-brand-hover"
              >
                Save
              </button>
              <button
                type="button"
                disabled={busy}
                onClick={() => {
                  setEditing(false);
                  setFormError(null);
                }}
                className="rounded-full border border-[var(--border)] px-4 py-2 text-sm font-medium"
              >
                Cancel
              </button>
            </div>
          </div>
        ) : null}
      </div>
    </div>
  );
}
