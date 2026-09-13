"use client";

import { useState } from "react";
import {
  reversalLedgerApi,
  type ReversalLedgerEntryDto,
} from "@/lib/api";
import { formatINR } from "@/lib/format";
import {
  STATUTORY_REASON_LABELS,
  paiseToRupees,
} from "./reversalLedgerLogic";

interface ReversalAuthorizeModalProps {
  isOpen: boolean;
  onClose: () => void;
  onSuccess: (updated: ReversalLedgerEntryDto) => void;
  entry: ReversalLedgerEntryDto | null;
  runId: string;
  authToken: string;
}

export function ReversalAuthorizeModal({
  isOpen,
  onClose,
  onSuccess,
  entry,
  runId,
  authToken,
}: ReversalAuthorizeModalProps) {
  const [notes, setNotes] = useState("");
  const [confirmedDeclaration, setConfirmedDeclaration] = useState(false);
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [errorMessage, setErrorMessage] = useState<string | null>(null);

  if (!isOpen || !entry) return null;

  const totalReversed = paiseToRupees(entry.reversed_total_tax_paise);
  const evidence = entry.condition_evidence || {};

  const handleAuthorize = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!confirmedDeclaration) {
      setErrorMessage("Please confirm the statutory eligibility declaration.");
      return;
    }

    if (entry.status === "OPEN") {
      setErrorMessage("Cannot authorize reclaim while condition is pending. Evidence must be verified first.");
      return;
    }

    setIsSubmitting(true);
    setErrorMessage(null);

    try {
      const updated = await reversalLedgerApi.authorizeReclaim(
        authToken,
        runId,
        entry.id,
        { notes: notes.trim() || undefined }
      );
      onSuccess(updated);
      onClose();
    } catch (err: any) {
      setErrorMessage(
        err?.detail || err?.message || "Failed to authorize reclaim."
      );
    } finally {
      setIsSubmitting(false);
    }
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 backdrop-blur-sm p-4">
      <div className="w-full max-w-lg rounded-2xl border border-[#E5E7EB] bg-white p-6 shadow-2xl animate-in fade-in zoom-in-95 duration-150">
        <div className="flex items-start justify-between border-b border-[#E5E7EB] pb-4">
          <div>
            <span className="inline-flex items-center gap-1 rounded bg-emerald-50 px-2 py-0.5 text-[11px] font-bold text-emerald-800 uppercase tracking-wider">
              Statutory Signoff
            </span>
            <h2 className="mt-1 text-[17px] font-bold text-gray-900">
              Authorize ITC Reclaim
            </h2>
            <p className="mt-0.5 text-[12px] text-gray-500">
              Grant Chartered Accountant authorization to claim this reversed credit in Table 4(A)(5) and Table 4(D)(1).
            </p>
          </div>
          <button
            onClick={onClose}
            className="rounded-lg p-1.5 text-gray-400 hover:bg-gray-100 hover:text-gray-700"
          >
            ✕
          </button>
        </div>

        {/* Reversal Details */}
        <div className="mt-4 rounded-xl border border-gray-200 bg-gray-50/70 p-3.5 text-[12.5px] space-y-1.5">
          <div className="flex justify-between">
            <span className="text-gray-500">Document:</span>
            <span className="font-medium text-gray-900 font-mono">
              {entry.document_number} ({entry.supplier_gstin})
            </span>
          </div>
          <div className="flex justify-between">
            <span className="text-gray-500">Statutory Reason:</span>
            <span className="font-medium text-gray-900">
              {STATUTORY_REASON_LABELS[entry.statutory_reason] || entry.statutory_reason}
            </span>
          </div>
          <div className="flex justify-between border-t border-gray-200 pt-1.5">
            <span className="text-gray-600 font-medium">Reclaimable Tax:</span>
            <span className="font-bold text-emerald-800 tabular-nums">
              {formatINR(totalReversed)}
            </span>
          </div>
        </div>

        {/* Evidence Verification Review Section */}
        <div className="mt-3.5 rounded-xl border border-blue-200 bg-blue-50/50 p-3.5 text-[12px]">
          <h4 className="font-bold text-blue-950 uppercase tracking-wider text-[11px] mb-2 flex items-center gap-1.5">
            <span className="h-2 w-2 rounded-full bg-blue-600" />
            Verified Statutory Evidence On Record
          </h4>
          <div className="grid grid-cols-2 gap-2 text-gray-700">
            {evidence.payment_reference && (
              <div>
                <span className="text-gray-500 block text-[11px]">Payment Reference / UTR:</span>
                <span className="font-mono font-medium text-gray-900">{evidence.payment_reference}</span>
              </div>
            )}
            {evidence.payment_date && (
              <div>
                <span className="text-gray-500 block text-[11px]">Payment Date:</span>
                <span className="font-medium text-gray-900">{evidence.payment_date}</span>
              </div>
            )}
            {evidence.supplier_filing_arn && (
              <div>
                <span className="text-gray-500 block text-[11px]">Supplier GSTR-3B ARN:</span>
                <span className="font-mono font-medium text-gray-900">{evidence.supplier_filing_arn}</span>
              </div>
            )}
            {evidence.supplier_filing_date && (
              <div>
                <span className="text-gray-500 block text-[11px]">Supplier Filing Date:</span>
                <span className="font-medium text-gray-900">{evidence.supplier_filing_date}</span>
              </div>
            )}
            {evidence.receipt_evidence_ref && (
              <div>
                <span className="text-gray-500 block text-[11px]">Receipt / GRN Ref:</span>
                <span className="font-mono font-medium text-gray-900">{evidence.receipt_evidence_ref}</span>
              </div>
            )}
            {evidence.receipt_date && (
              <div>
                <span className="text-gray-500 block text-[11px]">Receipt Date:</span>
                <span className="font-medium text-gray-900">{evidence.receipt_date}</span>
              </div>
            )}
          </div>
          {evidence.notes && (
            <div className="mt-2 border-t border-blue-200/60 pt-1.5 text-[11.5px] text-gray-600">
              <span className="font-medium text-gray-700">Submitter Notes:</span> {evidence.notes}
            </div>
          )}
        </div>

        {errorMessage && (
          <div className="mt-3 rounded-xl border border-red-200 bg-red-50 p-3 text-[12.5px] text-red-800">
            {errorMessage}
          </div>
        )}

        <form onSubmit={handleAuthorize} className="mt-4 space-y-3.5">
          <div>
            <label className="block text-[12px] font-semibold text-gray-700 mb-1">
              CA Authorization Notes (Optional)
            </label>
            <textarea
              rows={2}
              placeholder="Signoff remarks, statutory verification confirmation, audit notes…"
              value={notes}
              onChange={(e) => setNotes(e.target.value)}
              className="w-full rounded-lg border border-gray-300 px-3 py-2 text-[13px] text-gray-900 focus:border-black focus:outline-none focus:ring-1 focus:ring-black"
            />
          </div>

          <div className="rounded-xl border border-gray-200 bg-gray-50 p-3">
            <label className="flex items-start gap-2.5 cursor-pointer">
              <input
                type="checkbox"
                required
                checked={confirmedDeclaration}
                onChange={(e) => setConfirmedDeclaration(e.target.checked)}
                className="mt-0.5 h-4 w-4 rounded border-gray-300 text-black focus:ring-black"
              />
              <span className="text-[12px] text-gray-700 leading-snug">
                I confirm that the statutory conditions under the CGST Act (Section 16 / Rules 37, 37A) have been verified against supporting documents, and this credit is authorized for Table 4 reclaim.
              </span>
            </label>
          </div>

          <div className="flex items-center justify-end gap-2 border-t border-[#E5E7EB] pt-4">
            <button
              type="button"
              onClick={onClose}
              disabled={isSubmitting}
              className="rounded-lg border border-gray-300 bg-white px-4 py-2 text-[12.5px] font-semibold text-gray-700 hover:bg-gray-50 transition"
            >
              Cancel
            </button>
            <button
              type="submit"
              disabled={isSubmitting || !confirmedDeclaration}
              className="inline-flex items-center gap-1.5 rounded-lg bg-emerald-700 px-4 py-2 text-[12.5px] font-semibold text-white hover:bg-emerald-800 transition disabled:opacity-50"
            >
              {isSubmitting ? "Authorizing…" : "Authorize Reclaim"}
            </button>
          </div>
        </form>
      </div>
    </div>
  );
}
