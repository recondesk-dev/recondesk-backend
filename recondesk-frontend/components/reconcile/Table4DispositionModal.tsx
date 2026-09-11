"use client";

import { useState } from "react";
import { gstr3bApi, Table4DispositionPayload } from "@/lib/api";

interface Table4DispositionModalProps {
  runId: string;
  authToken: string;
  isOpen: boolean;
  onClose: () => void;
  onSuccess: () => void;
  blockingRecords: Array<{
    record_id: string;
    exception_type: string;
    supplier_name?: string;
    invoice_number?: string;
    amount?: number;
    reason?: string;
  }>;
}

export function Table4DispositionModal({
  runId,
  authToken,
  isOpen,
  onClose,
  onSuccess,
  blockingRecords,
}: Table4DispositionModalProps) {
  const [selectedRecordId, setSelectedRecordId] = useState<string>(
    blockingRecords[0]?.record_id || ""
  );
  const [disposition, setDisposition] = useState("CONFIRMED_BLOCKED");
  const [reason, setReason] = useState("");
  const [refDoc, setRefDoc] = useState("");
  const [statRef, setStatRef] = useState("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  if (!isOpen || blockingRecords.length === 0) return null;

  const currentRec = blockingRecords.find((b) => b.record_id === selectedRecordId) || blockingRecords[0];
  const isSec175 = currentRec?.exception_type === "SEC_17_5";
  const isRule37 = currentRec?.exception_type === "RULE_37";

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!reason || reason.trim().length < 5) {
      setError("Please provide a disposition explanation.");
      return;
    }

    setLoading(true);
    setError(null);

    const payload: Table4DispositionPayload = {
      record_id: currentRec.record_id,
      exception_type: currentRec.exception_type,
      disposition: disposition,
      reason: reason.trim(),
      reference_doc: refDoc.trim() || undefined,
      statutory_reference: statRef.trim() || undefined,
    };

    try {
      await gstr3bApi.recordDisposition(authToken, runId, payload);
      onSuccess();
      onClose();
    } catch (err: any) {
      setError(err?.detail || err?.message || "Failed to record disposition.");
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50 backdrop-blur-sm p-4">
      <div className="w-full max-w-lg rounded-2xl bg-white shadow-2xl overflow-hidden border border-[#E5E7EB]">
        <div className="border-b border-[#E5E7EB] px-6 py-4 flex items-center justify-between bg-[#FAFAFA]">
          <div>
            <h3 className="text-[16px] font-semibold text-gray-900">
              Record Audit Exception Disposition
            </h3>
            <p className="mt-0.5 text-[12px] text-gray-500">
              Required to clear finalization gate for ITC-affecting exceptions
            </p>
          </div>
          <button
            onClick={onClose}
            className="rounded-lg p-1.5 text-gray-400 hover:bg-gray-100 hover:text-gray-700"
          >
            <svg className="w-5 h-5" fill="none" viewBox="0 0 24 24" stroke="currentColor">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M6 18L18 6M6 6l12 12" />
            </svg>
          </button>
        </div>

        <form onSubmit={handleSubmit} className="p-6 space-y-4">
          {error && (
            <div className="rounded-lg bg-red-50 p-3 text-[12px] text-red-700 border border-red-200">
              {error}
            </div>
          )}

          <div>
            <label className="block text-[12px] font-medium text-gray-700 mb-1">
              Select Exception Invoice
            </label>
            <select
              value={selectedRecordId}
              onChange={(e) => setSelectedRecordId(e.target.value)}
              className="w-full rounded-lg border border-[#E5E7EB] px-3 py-2 text-[12px] text-gray-900 bg-white focus:border-black focus:outline-none"
            >
              {blockingRecords.map((b) => (
                <option key={b.record_id} value={b.record_id}>
                  {b.exception_type}: {b.supplier_name || "Supplier"} | #{b.invoice_number || "—"} (₹{b.amount || 0})
                </option>
              ))}
            </select>
          </div>

          <div className="rounded-lg bg-[#F8FAFC] p-3 border border-[#E5E7EB] text-[12px] text-gray-600">
            <span className="font-semibold text-gray-800">Issue: </span>
            {currentRec?.reason}
          </div>

          <div>
            <label className="block text-[12px] font-medium text-gray-700 mb-1">
              CA Disposition
            </label>
            <select
              value={disposition}
              onChange={(e) => setDisposition(e.target.value)}
              className="w-full rounded-lg border border-[#E5E7EB] px-3 py-2 text-[13px] font-semibold text-gray-900 bg-white focus:border-black focus:outline-none"
            >
              {isSec175 ? (
                <>
                  <option value="CONFIRMED_BLOCKED">
                    Confirmed Blocked under Sec 17(5) (Gross in 4A5, Reversed in 4B1)
                  </option>
                  <option value="STATUTORY_EXCEPTION">
                    Statutory Exception Eligible (e.g. Commercial Transport / Canteen under Law)
                  </option>
                </>
              ) : isRule37 ? (
                <>
                  <option value="REVERSED">
                    Confirmed Reversal in Table 4(B)(2) (Unpaid over 180 Days)
                  </option>
                  <option value="PAID_ELIGIBLE">
                    Payment Verified / Paid within 180 Days (Remains Eligible in 4A5)
                  </option>
                </>
              ) : (
                <>
                  <option value="BOOKED_AND_VERIFIED">
                    Booked & Verified in Books (Included in 4A5)
                  </option>
                  <option value="HELD_GOODS_NOT_RECEIVED">
                    Goods/Services Not Received (Hold on IMS, Exclude from 3B)
                  </option>
                  <option value="REJECTED_WRONG_GSTIN">
                    Vendor Billed Wrong GSTIN (Dispute on IMS, Exclude from 3B)
                  </option>
                  <option value="GOODS_IN_TRANSIT">
                    Goods In Transit with Active E-Way Bill (Hold for Next Month)
                  </option>
                  <option value="OTHER_EXPLAINED">
                    Other Non-Claimed Exception (Audited)
                  </option>
                </>
              )}
            </select>
          </div>

          <div>
            <label className="block text-[12px] font-medium text-gray-700 mb-1">
              Audit Note / Explanation
            </label>
            <textarea
              rows={2}
              value={reason}
              onChange={(e) => setReason(e.target.value)}
              placeholder="e.g. Executive dining expense confirmed blocked / Payment verified via bank voucher..."
              className="w-full rounded-lg border border-[#E5E7EB] px-3 py-2 text-[12px] focus:border-black focus:outline-none"
            />
          </div>

          <div className="grid grid-cols-2 gap-3">
            <div>
              <label className="block text-[12px] font-medium text-gray-700 mb-1">
                Reference Document
              </label>
              <input
                type="text"
                value={refDoc}
                onChange={(e) => setRefDoc(e.target.value)}
                placeholder="e.g. Bank Ref / ERP Voucher"
                className="w-full rounded-lg border border-[#E5E7EB] px-3 py-1.5 text-[12px] focus:border-black focus:outline-none"
              />
            </div>
            <div>
              <label className="block text-[12px] font-medium text-gray-700 mb-1">
                Statutory Clause (Optional)
              </label>
              <input
                type="text"
                value={statRef}
                onChange={(e) => setStatRef(e.target.value)}
                placeholder="e.g. Sec 17(5)(a) / Rule 37(1)"
                className="w-full rounded-lg border border-[#E5E7EB] px-3 py-1.5 text-[12px] focus:border-black focus:outline-none"
              />
            </div>
          </div>

          <div className="pt-3 flex justify-end gap-2 border-t border-[#E5E7EB]">
            <button
              type="button"
              onClick={onClose}
              className="rounded-lg border border-[#E5E7EB] px-4 py-2 text-[13px] font-medium text-gray-700 hover:bg-gray-50"
            >
              Cancel
            </button>
            <button
              type="submit"
              disabled={loading}
              className="rounded-lg bg-black px-4 py-2 text-[13px] font-semibold text-white hover:bg-gray-800 disabled:opacity-50"
            >
              {loading ? "Recording…" : "Save Disposition"}
            </button>
          </div>
        </form>
      </div>
    </div>
  );
}
