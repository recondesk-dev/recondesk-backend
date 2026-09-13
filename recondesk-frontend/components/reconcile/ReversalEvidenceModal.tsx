"use client";

import { useState } from "react";
import {
  reversalLedgerApi,
  type ReversalLedgerEntryDto,
  type ReversalConditionFulfillPayload,
} from "@/lib/api";
import { formatINR } from "@/lib/format";
import {
  STATUTORY_REASON_LABELS,
  paiseToRupees,
  validateEvidencePayload,
} from "./reversalLedgerLogic";

interface ReversalEvidenceModalProps {
  isOpen: boolean;
  onClose: () => void;
  onSuccess: (updated: ReversalLedgerEntryDto) => void;
  entry: ReversalLedgerEntryDto | null;
  runId: string;
  authToken: string;
}

export function ReversalEvidenceModal({
  isOpen,
  onClose,
  onSuccess,
  entry,
  runId,
  authToken,
}: ReversalEvidenceModalProps) {
  const [paymentRef, setPaymentRef] = useState("");
  const [paymentDate, setPaymentDate] = useState("");
  const [filingArn, setFilingArn] = useState("");
  const [filingDate, setFilingDate] = useState("");
  const [receiptRef, setReceiptRef] = useState("");
  const [receiptDate, setReceiptDate] = useState("");
  const [notes, setNotes] = useState("");

  const [isSubmitting, setIsSubmitting] = useState(false);
  const [errorMessage, setErrorMessage] = useState<string | null>(null);

  if (!isOpen || !entry) return null;

  const reason = entry.statutory_reason;
  const reasonLabel = STATUTORY_REASON_LABELS[reason] || reason;
  const totalReversed = paiseToRupees(entry.reversed_total_tax_paise);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setErrorMessage(null);

    const payload: ReversalConditionFulfillPayload = {
      notes: notes.trim() || undefined,
    };

    if (reason === "RULE_37_NON_PAYMENT") {
      payload.payment_reference = paymentRef.trim();
      payload.payment_date = paymentDate;
    } else if (reason === "RULE_37A_SUPPLIER_NON_FILING") {
      payload.supplier_filing_arn = filingArn.trim();
      payload.supplier_filing_date = filingDate;
    } else if (reason === "SECTION_16_2_B_NOT_RECEIVED") {
      payload.receipt_evidence_ref = receiptRef.trim();
      payload.receipt_date = receiptDate;
    } else {
      payload.receipt_evidence_ref = receiptRef.trim() || paymentRef.trim() || undefined;
      payload.receipt_date = receiptDate || paymentDate || undefined;
    }

    const preflight = validateEvidencePayload(reason, payload);
    if (!preflight.isValid) {
      setErrorMessage(preflight.errorMessage || "Please provide required statutory evidence.");
      return;
    }

    setIsSubmitting(true);
    try {
      const updated = await reversalLedgerApi.fulfillCondition(
        authToken,
        runId,
        entry.id,
        payload
      );
      onSuccess(updated);
      onClose();
    } catch (err: any) {
      setErrorMessage(
        err?.detail || err?.message || "Failed to record condition fulfillment."
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
            <span className="inline-flex items-center gap-1 rounded bg-blue-50 px-2 py-0.5 text-[11px] font-bold text-blue-800 uppercase tracking-wider">
              Evidence Workflow
            </span>
            <h2 className="mt-1 text-[17px] font-bold text-gray-900">
              Submit Statutory Reclaim Evidence
            </h2>
            <p className="mt-0.5 text-[12px] text-gray-500">
              Transition reversal from <span className="font-semibold text-gray-700">Condition pending</span> to <span className="font-semibold text-blue-700">Condition verified</span>.
            </p>
          </div>
          <button
            onClick={onClose}
            className="rounded-lg p-1.5 text-gray-400 hover:bg-gray-100 hover:text-gray-700"
          >
            ✕
          </button>
        </div>

        {/* Invoice Summary Card */}
        <div className="mt-4 rounded-xl border border-gray-200 bg-gray-50/70 p-3.5 text-[12.5px] space-y-1.5">
          <div className="flex justify-between">
            <span className="text-gray-500">Document:</span>
            <span className="font-medium text-gray-900 font-mono">
              {entry.document_number || "—"} ({entry.document_type || "INVOICE"})
            </span>
          </div>
          <div className="flex justify-between">
            <span className="text-gray-500">Supplier GSTIN:</span>
            <span className="font-medium text-gray-900 font-mono">
              {entry.supplier_gstin} {entry.supplier_legal_name ? `• ${entry.supplier_legal_name}` : ""}
            </span>
          </div>
          <div className="flex justify-between">
            <span className="text-gray-500">Reversal Period:</span>
            <span className="font-medium text-gray-900">{entry.reversal_tax_period}</span>
          </div>
          <div className="flex justify-between border-t border-gray-200 pt-1.5">
            <span className="text-gray-600 font-medium">Reversed Tax:</span>
            <span className="font-bold text-gray-900 tabular-nums">
              {formatINR(totalReversed)}
            </span>
          </div>
        </div>

        {/* Statutory Category Header */}
        <div className="mt-3 rounded-lg bg-blue-50/50 p-2.5 border border-blue-100">
          <p className="text-[11.5px] font-semibold text-blue-900">
            Category: {reasonLabel}
          </p>
        </div>

        {errorMessage && (
          <div className="mt-3 rounded-xl border border-red-200 bg-red-50 p-3 text-[12.5px] text-red-800">
            {errorMessage}
          </div>
        )}

        <form onSubmit={handleSubmit} className="mt-4 space-y-3.5">
          {reason === "RULE_37_NON_PAYMENT" && (
            <>
              <div>
                <label className="block text-[12px] font-semibold text-gray-700 mb-1">
                  Payment Reference / UTR Number <span className="text-red-500">*</span>
                </label>
                <input
                  type="text"
                  required
                  placeholder="e.g. UTR12345678 or Bank Txn Ref"
                  value={paymentRef}
                  onChange={(e) => setPaymentRef(e.target.value)}
                  className="w-full rounded-lg border border-gray-300 px-3 py-2 text-[13px] text-gray-900 focus:border-black focus:outline-none focus:ring-1 focus:ring-black"
                />
              </div>
              <div>
                <label className="block text-[12px] font-semibold text-gray-700 mb-1">
                  Payment Date <span className="text-red-500">*</span>
                </label>
                <input
                  type="date"
                  required
                  value={paymentDate}
                  onChange={(e) => setPaymentDate(e.target.value)}
                  className="w-full rounded-lg border border-gray-300 px-3 py-2 text-[13px] text-gray-900 focus:border-black focus:outline-none focus:ring-1 focus:ring-black"
                />
              </div>
            </>
          )}

          {reason === "RULE_37A_SUPPLIER_NON_FILING" && (
            <>
              <div className="rounded-lg bg-amber-50 p-2 border border-amber-200 text-[11.5px] text-amber-900">
                ⚠️ Confirm supplier GSTR-3B has been filed on GST Portal with valid ARN before fulfilling.
              </div>
              <div>
                <label className="block text-[12px] font-semibold text-gray-700 mb-1">
                  Supplier GSTR-3B Filing ARN <span className="text-red-500">*</span>
                </label>
                <input
                  type="text"
                  required
                  placeholder="e.g. AA2703240012345"
                  value={filingArn}
                  onChange={(e) => setFilingArn(e.target.value)}
                  className="w-full rounded-lg border border-gray-300 px-3 py-2 text-[13px] text-gray-900 focus:border-black focus:outline-none focus:ring-1 focus:ring-black"
                />
              </div>
              <div>
                <label className="block text-[12px] font-semibold text-gray-700 mb-1">
                  Supplier Filing Date <span className="text-red-500">*</span>
                </label>
                <input
                  type="date"
                  required
                  value={filingDate}
                  onChange={(e) => setFilingDate(e.target.value)}
                  className="w-full rounded-lg border border-gray-300 px-3 py-2 text-[13px] text-gray-900 focus:border-black focus:outline-none focus:ring-1 focus:ring-black"
                />
              </div>
            </>
          )}

          {reason === "SECTION_16_2_B_NOT_RECEIVED" && (
            <>
              <div className="rounded-lg bg-amber-50 p-2 border border-amber-200 text-[11.5px] text-amber-900">
                ⚠️ Confirmation requires physical GRN or verified delivery document. Internal ERP transit tags are not statutory proof.
              </div>
              <div>
                <label className="block text-[12px] font-semibold text-gray-700 mb-1">
                  GRN / Delivery Challan Ref <span className="text-red-500">*</span>
                </label>
                <input
                  type="text"
                  required
                  placeholder="e.g. GRN-2024-8899 / DC-102"
                  value={receiptRef}
                  onChange={(e) => setReceiptRef(e.target.value)}
                  className="w-full rounded-lg border border-gray-300 px-3 py-2 text-[13px] text-gray-900 focus:border-black focus:outline-none focus:ring-1 focus:ring-black"
                />
              </div>
              <div>
                <label className="block text-[12px] font-semibold text-gray-700 mb-1">
                  Receipt Date <span className="text-red-500">*</span>
                </label>
                <input
                  type="date"
                  required
                  value={receiptDate}
                  onChange={(e) => setReceiptDate(e.target.value)}
                  className="w-full rounded-lg border border-gray-300 px-3 py-2 text-[13px] text-gray-900 focus:border-black focus:outline-none focus:ring-1 focus:ring-black"
                />
              </div>
            </>
          )}

          {reason !== "RULE_37_NON_PAYMENT" &&
            reason !== "RULE_37A_SUPPLIER_NON_FILING" &&
            reason !== "SECTION_16_2_B_NOT_RECEIVED" && (
              <>
                <div>
                  <label className="block text-[12px] font-semibold text-gray-700 mb-1">
                    Statutory Evidence Reference <span className="text-red-500">*</span>
                  </label>
                  <input
                    type="text"
                    required
                    placeholder="Reference document / challan"
                    value={receiptRef}
                    onChange={(e) => setReceiptRef(e.target.value)}
                    className="w-full rounded-lg border border-gray-300 px-3 py-2 text-[13px] text-gray-900 focus:border-black focus:outline-none focus:ring-1 focus:ring-black"
                  />
                </div>
                <div>
                  <label className="block text-[12px] font-semibold text-gray-700 mb-1">
                    Evidence Date <span className="text-red-500">*</span>
                  </label>
                  <input
                    type="date"
                    required
                    value={receiptDate}
                    onChange={(e) => setReceiptDate(e.target.value)}
                    className="w-full rounded-lg border border-gray-300 px-3 py-2 text-[13px] text-gray-900 focus:border-black focus:outline-none focus:ring-1 focus:ring-black"
                  />
                </div>
              </>
            )}

          <div>
            <label className="block text-[12px] font-semibold text-gray-700 mb-1">
              CA / Compliance Notes (Optional)
            </label>
            <textarea
              rows={2}
              placeholder="Internal verification notes, bank statement page, ledger cross-ref…"
              value={notes}
              onChange={(e) => setNotes(e.target.value)}
              className="w-full rounded-lg border border-gray-300 px-3 py-2 text-[13px] text-gray-900 focus:border-black focus:outline-none focus:ring-1 focus:ring-black"
            />
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
              disabled={isSubmitting}
              className="inline-flex items-center gap-1.5 rounded-lg bg-black px-4 py-2 text-[12.5px] font-semibold text-white hover:bg-gray-800 transition disabled:opacity-50"
            >
              {isSubmitting ? (
                <>
                  <svg className="h-3.5 w-3.5 animate-spin" fill="none" viewBox="0 0 24 24">
                    <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
                    <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8v8z" />
                  </svg>
                  Recording…
                </>
              ) : (
                "Record Condition Fulfillment"
              )}
            </button>
          </div>
        </form>
      </div>
    </div>
  );
}
