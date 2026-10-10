"use client";

import { useEffect, useState } from "react";
import { Check, Edit3, X, AlertCircle } from "lucide-react";
import type { FilingPendingReviewItem } from "@/lib/api";
import type { Gstr1PatchRecord } from "@/lib/gstr1PatchVoucher";
import { formatINR } from "@/lib/format";

const INDIAN_STATES = [
  { code: "01", name: "01-Jammu and Kashmir" },
  { code: "02", name: "02-Himachal Pradesh" },
  { code: "03", name: "03-Punjab" },
  { code: "04", name: "04-Chandigarh" },
  { code: "05", name: "05-Uttarakhand" },
  { code: "06", name: "06-Haryana" },
  { code: "07", name: "07-Delhi" },
  { code: "08", name: "08-Rajasthan" },
  { code: "09", name: "09-Uttar Pradesh" },
  { code: "10", name: "10-Bihar" },
  { code: "11", name: "11-Sikkim" },
  { code: "12", name: "12-Arunachal Pradesh" },
  { code: "13", name: "13-Nagaland" },
  { code: "14", name: "14-Manipur" },
  { code: "15", name: "15-Mizoram" },
  { code: "16", name: "16-Tripura" },
  { code: "17", name: "17-Meghalaya" },
  { code: "18", name: "18-Assam" },
  { code: "19", name: "19-West Bengal" },
  { code: "20", name: "20-Jharkhand" },
  { code: "21", name: "21-Odisha" },
  { code: "22", name: "22-Chhattisgarh" },
  { code: "23", name: "23-Madhya Pradesh" },
  { code: "24", name: "24-Gujarat" },
  { code: "26", name: "26-Dadra and Nagar Haveli and Daman and Diu" },
  { code: "27", name: "27-Maharashtra" },
  { code: "29", name: "29-Karnataka" },
  { code: "30", name: "30-Goa" },
  { code: "31", name: "31-Lakshadweep" },
  { code: "32", name: "32-Kerala" },
  { code: "33", name: "33-Tamil Nadu" },
  { code: "34", name: "34-Puducherry" },
  { code: "35", name: "35-Andaman and Nicobar Islands" },
  { code: "36", name: "36-Telangana" },
  { code: "37", name: "37-Andhra Pradesh" },
  { code: "38", name: "38-Ladakh" },
  { code: "97", name: "97-Other Territory" },
];

export function QuickPatchModal({
  isOpen,
  onClose,
  item,
  existingPatch,
  onApplyPatch,
}: {
  isOpen: boolean;
  onClose: () => void;
  item: FilingPendingReviewItem | null;
  existingPatch?: Gstr1PatchRecord | null;
  onApplyPatch: (patch: Gstr1PatchRecord) => void;
}) {
  const ctx = (item?.context || {}) as Record<string, unknown>;

  const invoiceNum = String(
    ctx.invoice_number_raw || ctx.invoice_number || ""
  );
  const rowNumber = ctx.row_number != null ? Number(ctx.row_number) : undefined;
  const invDate = String(ctx.invoice_date || "");
  const taxablePaise =
    ctx.taxable_amount_paise != null ? Number(ctx.taxable_amount_paise) : undefined;

  const initialGstin = String(
    existingPatch?.patch_data.gstin || ctx.gstin || ""
  ).trim();
  const initialPos = String(
    existingPatch?.patch_data.place_of_supply ||
      ctx.place_of_supply ||
      ctx.pos ||
      ""
  ).trim();
  const initialInvType = String(
    existingPatch?.patch_data.invoice_type ||
      item?.proposed_inv_typ ||
      ctx.invoice_type_raw ||
      ctx.invoice_type ||
      "B2B"
  ).trim().toUpperCase();
  const initialReason =
    existingPatch?.reason ||
    "Corrected for GSTR-1 filing; please reconcile in ERP books";

  const [gstin, setGstin] = useState(initialGstin);
  const [pos, setPos] = useState(initialPos);
  const [invType, setInvType] = useState(initialInvType);
  const [noteType, setNoteType] = useState(
    String(existingPatch?.patch_data.note_type || ctx.note_type || "C")
  );
  const [exportType, setExportType] = useState(
    String(existingPatch?.patch_data.export_type || ctx.export_type_raw || "WPAY")
  );
  const [reason, setReason] = useState(initialReason);

  useEffect(() => {
    if (isOpen && item) {
      setGstin(
        String(existingPatch?.patch_data.gstin || ctx.gstin || "").trim()
      );
      setPos(
        String(
          existingPatch?.patch_data.place_of_supply ||
            ctx.place_of_supply ||
            ctx.pos ||
            ""
        ).trim()
      );
      setInvType(
        String(
          existingPatch?.patch_data.invoice_type ||
            item?.proposed_inv_typ ||
            ctx.invoice_type_raw ||
            ctx.invoice_type ||
            "B2B"
        ).trim().toUpperCase()
      );
      setNoteType(
        String(existingPatch?.patch_data.note_type || ctx.note_type || "C")
      );
      setExportType(
        String(existingPatch?.patch_data.export_type || ctx.export_type_raw || "WPAY")
      );
      setReason(
        existingPatch?.reason ||
          "Corrected for GSTR-1 filing; please reconcile in ERP books"
      );
    }
  }, [isOpen, item, existingPatch, ctx]);

  if (!isOpen || !item) return null;

  const isGstinValid =
    !gstin ||
    /^[0-9]{2}[A-Z]{5}[0-9]{4}[A-Z]{1}[1-9A-Z]{1}Z[0-9A-Z]{1}$/i.test(gstin.trim());

  const handleSave = () => {
    const cleanGstin = gstin.trim().toUpperCase();
    const cleanPos = pos.trim();
    const cleanInvType = invType.trim().toUpperCase();

    // Determine field modified for audit diff
    let fieldModified: Gstr1PatchRecord["field_name"] = "invoice_type";
    let origVal = String(ctx.invoice_type_raw || ctx.invoice_type || "");
    let patchVal = cleanInvType;

    if (cleanGstin !== String(ctx.gstin || "").trim().toUpperCase()) {
      fieldModified = "gstin";
      origVal = String(ctx.gstin || "");
      patchVal = cleanGstin;
    } else if (cleanPos !== String(ctx.place_of_supply || ctx.pos || "").trim()) {
      fieldModified = "place_of_supply";
      origVal = String(ctx.place_of_supply || ctx.pos || "");
      patchVal = cleanPos;
    }

    const patchRecord: Gstr1PatchRecord = {
      row_number: rowNumber,
      invoice_number: invoiceNum,
      invoice_date: invDate,
      taxable_amount_paise: taxablePaise,
      field_name: fieldModified,
      original_value: origVal,
      patched_value: patchVal,
      reason: reason.trim(),
      timestamp: new Date().toLocaleString("en-IN", { timeZone: "Asia/Kolkata" }),
      patch_data: {
        row_number: rowNumber,
        invoice_number: invoiceNum,
        gstin: cleanGstin || undefined,
        place_of_supply: cleanPos || undefined,
        invoice_type: cleanInvType || undefined,
        note_type: invType.includes("NOTE") ? noteType : undefined,
        export_type: cleanInvType === "EXPORT" ? exportType : undefined,
      },
    };

    onApplyPatch(patchRecord);
    onClose();
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-4 backdrop-blur-sm">
      <div className="relative w-full max-w-lg rounded-2xl bg-white p-6 shadow-2xl ring-1 ring-black/10">
        <div className="flex items-start justify-between border-b border-gray-100 pb-3">
          <div>
            <div className="flex items-center gap-2">
              <span className="inline-flex items-center gap-1 rounded-full bg-blue-50 px-2.5 py-0.5 text-[11px] font-bold text-blue-700">
                <Edit3 className="h-3 w-3" />
                Quick-Patch
              </span>
              <span className="text-xs text-gray-500">
                Row #{rowNumber ?? "—"}
              </span>
            </div>
            <h3 className="mt-1 text-base font-bold text-[var(--ink)]">
              Patch Invoice: {invoiceNum}
            </h3>
          </div>
          <button
            type="button"
            onClick={onClose}
            className="rounded-full p-1 text-gray-400 hover:bg-gray-100 hover:text-gray-700"
          >
            <X className="h-4 w-4" />
          </button>
        </div>

        {/* Issue Alert Context */}
        <div className="mt-4 rounded-xl bg-amber-50/80 p-3 ring-1 ring-amber-200/60">
          <div className="flex items-start gap-2">
            <AlertCircle className="mt-0.5 h-4 w-4 shrink-0 text-amber-700" />
            <div className="text-[12px] text-amber-900">
              <span className="font-semibold">Reason Held: </span>
              <span>{item.reason}</span>
              {taxablePaise != null ? (
                <span className="block mt-0.5 text-amber-800">
                  Taxable Value: {formatINR(taxablePaise / 100)}
                </span>
              ) : null}
            </div>
          </div>
        </div>

        {/* Patch Form */}
        <div className="mt-4 space-y-3.5">
          <div>
            <label className="block text-[12px] font-semibold text-gray-700">
              Recipient GSTIN
            </label>
            <input
              type="text"
              maxLength={15}
              value={gstin}
              onChange={(e) => setGstin(e.target.value.toUpperCase())}
              placeholder="e.g. 27AAPFU0939F1ZV"
              className="mt-1 h-9 w-full rounded-lg border border-gray-300 px-3 font-mono text-[13px] uppercase outline-none focus:border-blue-500 focus:ring-1 focus:ring-blue-500"
            />
            {gstin && !isGstinValid ? (
              <p className="mt-1 text-[11px] text-red-600">
                Invalid GSTIN format (must be 15 alphanumeric characters).
              </p>
            ) : null}
          </div>

          <div>
            <label className="block text-[12px] font-semibold text-gray-700">
              Place of Supply (POS)
            </label>
            <select
              value={pos}
              onChange={(e) => setPos(e.target.value)}
              className="mt-1 h-9 w-full rounded-lg border border-gray-300 bg-white px-3 text-[13px] outline-none focus:border-blue-500"
            >
              <option value="">Select state / POS code…</option>
              {INDIAN_STATES.map((s) => (
                <option key={s.code} value={s.name}>
                  {s.name}
                </option>
              ))}
            </select>
          </div>

          <div className="grid grid-cols-2 gap-3">
            <div>
              <label className="block text-[12px] font-semibold text-gray-700">
                Invoice Classification
              </label>
              <select
                value={invType}
                onChange={(e) => setInvType(e.target.value)}
                className="mt-1 h-9 w-full rounded-lg border border-gray-300 bg-white px-3 text-[13px] outline-none focus:border-blue-500"
              >
                <option value="B2B">B2B (Regular)</option>
                <option value="B2CS">B2C (Small / Retail)</option>
                <option value="B2CL">B2C (Large Interstate)</option>
                <option value="EXPORT">Export</option>
                <option value="CREDIT_NOTE">Credit Note</option>
                <option value="DEBIT_NOTE">Debit Note</option>
              </select>
            </div>

            {invType === "EXPORT" ? (
              <div>
                <label className="block text-[12px] font-semibold text-gray-700">
                  Export Type
                </label>
                <select
                  value={exportType}
                  onChange={(e) => setExportType(e.target.value)}
                  className="mt-1 h-9 w-full rounded-lg border border-gray-300 bg-white px-3 text-[13px] outline-none"
                >
                  <option value="WPAY">WPAY (With Payment)</option>
                  <option value="WOPAY">WOPAY (Without Payment)</option>
                </select>
              </div>
            ) : invType.includes("NOTE") ? (
              <div>
                <label className="block text-[12px] font-semibold text-gray-700">
                  Note Type
                </label>
                <select
                  value={noteType}
                  onChange={(e) => setNoteType(e.target.value)}
                  className="mt-1 h-9 w-full rounded-lg border border-gray-300 bg-white px-3 text-[13px] outline-none"
                >
                  <option value="C">Credit Note (C)</option>
                  <option value="D">Debit Note (D)</option>
                </select>
              </div>
            ) : (
              <div>
                <label className="block text-[12px] font-semibold text-gray-500">
                  Status in Filing
                </label>
                <div className="mt-1 flex h-9 items-center rounded-lg bg-gray-50 px-3 text-[12px] font-medium text-emerald-700">
                  <Check className="mr-1.5 h-3.5 w-3.5" />
                  Moves to Save Payload
                </div>
              </div>
            )}
          </div>

          <div>
            <label className="block text-[12px] font-semibold text-gray-700">
              Audit Reason / Note for Client Books
            </label>
            <input
              type="text"
              value={reason}
              onChange={(e) => setReason(e.target.value)}
              placeholder="e.g. Corrected GSTIN typo per customer copy"
              className="mt-1 h-9 w-full rounded-lg border border-gray-300 px-3 text-[13px] outline-none focus:border-blue-500"
            />
            <p className="mt-1 text-[11px] text-gray-400">
              Logged in the downloadable Tally XML and ERP audit reconciliation sheet.
            </p>
          </div>
        </div>

        {/* Modal Actions */}
        <div className="mt-6 flex items-center justify-end gap-3 border-t border-gray-100 pt-4">
          <button
            type="button"
            onClick={onClose}
            className="rounded-full px-4 py-2 text-[13px] font-medium text-gray-600 hover:bg-gray-100"
          >
            Cancel
          </button>
          <button
            type="button"
            onClick={handleSave}
            disabled={!isGstinValid}
            className="inline-flex items-center gap-1.5 rounded-full bg-[var(--ink)] px-5 py-2 text-[13px] font-semibold text-white shadow-sm hover:opacity-95 disabled:opacity-40"
          >
            <Check className="h-4 w-4" />
            Apply Quick-Patch
          </button>
        </div>
      </div>
    </div>
  );
}
