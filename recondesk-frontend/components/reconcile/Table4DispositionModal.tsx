"use client";

import { useState, useEffect } from "react";
import { gstr3bApi, Table4DispositionPayload, Table4BlockingRecordItem } from "@/lib/api";

export type { Table4BlockingRecordItem };

interface Table4DispositionModalProps {
  runId: string;
  authToken: string;
  isOpen: boolean;
  onClose: () => void;
  onSuccess: (disposition?: string, table4Effect?: string) => void;
  blockingRecords?: Table4BlockingRecordItem[];
  targetRecord?: Table4BlockingRecordItem | null;
}

export function Table4DispositionModal({
  runId,
  authToken,
  isOpen,
  onClose,
  onSuccess,
  blockingRecords = [],
  targetRecord = null,
}: Table4DispositionModalProps) {
  const records = targetRecord ? [targetRecord] : blockingRecords;
  const [selectedRecordId, setSelectedRecordId] = useState<string>(
    targetRecord?.record_id || records[0]?.record_id || ""
  );
  const [disposition, setDisposition] = useState("CONFIRMED_BLOCKED");
  const [reason, setReason] = useState("");
  const [refDoc, setRefDoc] = useState("");
  const [statRef, setStatRef] = useState("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const currentRec = records.find((b) => b.record_id === selectedRecordId) || records[0];
  const isSec175 = currentRec?.exception_type === "SEC_17_5";
  const isRule37 = currentRec?.exception_type === "RULE_37";

  useEffect(() => {
    if (targetRecord) {
      setSelectedRecordId(targetRecord.record_id);
    } else if (records.length > 0 && !records.some((r) => r.record_id === selectedRecordId)) {
      setSelectedRecordId(records[0].record_id);
    }
  }, [targetRecord, isOpen, records]);

  useEffect(() => {
    if (isSec175) {
      setDisposition("CONFIRMED_BLOCKED");
      setStatRef((prev) => prev || "Sec 17(5)");
    } else if (isRule37) {
      setDisposition("REVERSED");
      setStatRef((prev) => prev || "Rule 37(1)");
    } else {
      setDisposition("BOOKED_AND_VERIFIED");
    }
    setError(null);
  }, [selectedRecordId, currentRec?.exception_type, isSec175, isRule37]);

  if (!isOpen || records.length === 0) return null;

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!reason || reason.trim().length < 5) {
      setError("Please provide a disposition explanation (minimum 5 characters).");
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

    let table4Effect = "4A5";
    if (disposition === "CONFIRMED_BLOCKED" || disposition === "INELIGIBLE") {
      table4Effect = "4B1";
    } else if (disposition === "REVERSED" || disposition === "REVERSAL_CONFIRMED") {
      table4Effect = "4B2";
    } else if (
      disposition === "HELD_GOODS_NOT_RECEIVED" ||
      disposition === "HOLD" ||
      disposition === "REJECTED_WRONG_GSTIN"
    ) {
      table4Effect = "EXCLUDED";
    }

    try {
      await gstr3bApi.recordDisposition(authToken, runId, payload);
      onSuccess(disposition, table4Effect);
      onClose();
    } catch (err: any) {
      if (
        err?.status === 409 ||
        err?.detail?.includes("immutable") ||
        err?.message?.includes("immutable")
      ) {
        setError("This reconciliation run has already been finalized and cannot be modified.");
      } else if (err?.status === 422 || err?.detail?.includes("validation")) {
        setError("Invalid disposition input: please verify all required fields.");
      } else {
        setError(err?.detail || err?.message || "Failed to record disposition.");
      }
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

          {targetRecord || records.length === 1 ? (
            <div className="rounded-xl border border-gray-200 bg-gray-50/70 p-3.5 space-y-1.5">
              <div className="flex items-center justify-between">
                <span className="text-xs font-semibold text-gray-900">
                  Invoice #{currentRec?.invoice_number || "—"}
                </span>
                <span className="rounded-md bg-white px-2 py-0.5 text-xs font-bold text-gray-800 border border-gray-200 shadow-sm">
                  ₹{Number(currentRec?.amount || 0).toLocaleString("en-IN")}
                </span>
              </div>
              <div className="flex items-center justify-between text-xs text-gray-600">
                <span>{currentRec?.supplier_name || "Supplier"}</span>
                <span className="font-mono text-[11px] font-semibold text-amber-700 bg-amber-50 px-1.5 py-0.5 rounded">
                  {currentRec?.exception_type}
                </span>
              </div>
            </div>
          ) : (
            <div>
              <label className="block text-[12px] font-medium text-gray-700 mb-1">
                Select Exception Invoice ({records.length} requiring disposition)
              </label>
              <select
                value={selectedRecordId}
                onChange={(e) => setSelectedRecordId(e.target.value)}
                className="w-full rounded-lg border border-[#E5E7EB] px-3 py-2 text-[12px] text-gray-900 bg-white focus:border-black focus:outline-none"
              >
                {records.map((b) => (
                  <option key={b.record_id} value={b.record_id}>
                    {b.exception_type}: {b.supplier_name || "Supplier"} | #{b.invoice_number || "—"} (₹{b.amount || 0})
                  </option>
                ))}
              </select>
            </div>
          )}

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
