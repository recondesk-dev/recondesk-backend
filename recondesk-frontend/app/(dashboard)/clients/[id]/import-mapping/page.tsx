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
    <div className="dashboard-card animate-pulse space-y-3 p-6">
      <div className="h-4 w-48 rounded-full bg-gray-100" />
      <div className="h-10 w-full rounded-2xl bg-gray-100" />
      <div className="h-32 w-full rounded-2xl bg-gray-100" />
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
      <div className="rounded-[1.25rem] bg-red-50 px-5 py-4 text-sm text-red-800">
        Could not load client.
      </div>
    );
  }

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-lg font-semibold tracking-tight text-[var(--ink)]">
          Import Mapping
        </h1>
        <p className="mt-1 text-sm text-gray-500">
          Saved purchase-register column mapping for{" "}
          <strong className="font-semibold text-[var(--ink)]">
            {client.trade_name || client.gstin}
          </strong>
          . Used automatically on the next upload when headers match.
        </p>
      </div>

      {mappingError ? (
        <div className="rounded-[1.25rem] bg-red-50 px-5 py-4 text-sm text-red-800">
          Could not load saved mapping.
        </div>
      ) : null}

      <div className="dashboard-card p-6">
        {!rows?.length && !editing ? (
          <div className="flex flex-col items-start gap-4 rounded-2xl bg-[#F7F7F8] px-5 py-8">
            <p className="text-sm text-gray-500">
              No saved mapping yet. Map columns during the next purchase-register upload, or add
              one here.
            </p>
            <button
              type="button"
              onClick={startEdit}
              className="rounded-full bg-[var(--ink)] px-4 py-2 text-sm font-semibold text-white transition-opacity hover:opacity-90"
            >
              Add mapping
            </button>
          </div>
        ) : null}

        {rows?.length && !editing ? (
          <div className="space-y-5">
            <div className="overflow-hidden rounded-[1.25rem] ring-1 ring-[#F0F0F0]">
              <table className="w-full border-collapse text-left text-sm">
                <thead>
                  <tr className="border-b border-[#F0F0F0] text-[11px] font-medium uppercase tracking-widest text-gray-400">
                    <th className="px-5 py-4">Target field</th>
                    <th className="px-5 py-4">Source column</th>
                  </tr>
                </thead>
                <tbody>
                  {rows.map((r) => (
                    <tr
                      key={r.target_field}
                      className="border-b border-[#F0F0F0] transition-colors last:border-b-0 hover:bg-[#F7F7F8]"
                    >
                      <td className="px-5 py-3.5 font-medium text-[var(--ink)]">
                        {LABELS[r.target_field] ?? r.target_field}
                        {REQUIRED.includes(r.target_field) ? (
                          <span className="text-red-600">*</span>
                        ) : null}
                      </td>
                      <td className="px-5 py-3.5 font-mono text-xs text-gray-600">
                        {r.source_column_name}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            <div className="flex flex-wrap gap-2">
              <button
                type="button"
                onClick={startEdit}
                disabled={busy}
                className="rounded-full bg-[#F5F5F6] px-4 py-2 text-sm font-semibold text-[var(--ink)] transition-colors hover:bg-gray-200/70 disabled:opacity-40"
              >
                Edit
              </button>
              <button
                type="button"
                onClick={() => void onDelete()}
                disabled={busy}
                className="rounded-full bg-red-50 px-4 py-2 text-sm font-semibold text-red-700 transition-colors hover:bg-red-100 disabled:opacity-40"
              >
                Delete
              </button>
            </div>
          </div>
        ) : null}

        {editing ? (
          <div className="space-y-5">
            <p className="text-sm text-gray-500">
              Enter the exact column header from this client&apos;s purchase register for each
              field.
            </p>
            <div className="space-y-3">
              {TARGET_FIELDS.map((tf) => (
                <label key={tf} className="flex flex-col gap-1.5 text-sm sm:flex-row sm:items-center">
                  <span className="w-40 font-medium text-[var(--ink)]">
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
                    className="flex-1 rounded-full border-0 bg-[#F5F5F6] px-4 py-2.5 text-sm font-medium text-[var(--ink)] placeholder:text-gray-400 focus:outline-none focus:ring-2 focus:ring-black/10"
                  />
                </label>
              ))}
            </div>
            <p className="text-xs text-gray-400">
              * Required: GSTIN, invoice number, invoice date, taxable value, and at least one of
              CGST / SGST / IGST / Cess.
            </p>
            {formError ? (
              <div className="rounded-[1.25rem] bg-red-50 px-5 py-3 text-sm text-red-800">
                {formError}
              </div>
            ) : null}
            <div className="flex flex-wrap gap-2">
              <button
                type="button"
                disabled={busy || !canSave}
                onClick={() => void onSave()}
                className="rounded-full bg-[var(--ink)] px-4 py-2 text-sm font-semibold text-white transition-opacity hover:opacity-90 disabled:opacity-50"
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
                className="rounded-full bg-[#F5F5F6] px-4 py-2 text-sm font-semibold text-[var(--ink)] transition-colors hover:bg-gray-200/70 disabled:opacity-40"
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
