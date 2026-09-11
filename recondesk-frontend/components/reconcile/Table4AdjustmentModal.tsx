"use client";

import { useState } from "react";
import { gstr3bApi, Table4AdjustmentPayload } from "@/lib/api";

interface Table4AdjustmentModalProps {
  runId: string;
  authToken: string;
  isOpen: boolean;
  onClose: () => void;
  onSuccess: () => void;
}

const CATEGORIES = [
  { value: "RULE_42_INPUTS", label: "Rule 42 — Common Input Credit Reversal (Exempt Turnover Ratio)", defaultRow: "4B1" },
  { value: "RULE_43_CAPITAL_GOODS", label: "Rule 43 — Capital Goods Common Credit Reversal", defaultRow: "4B1" },
  { value: "RULE_38_BANKING", label: "Rule 38 — Banking 50% Statutory Reversal", defaultRow: "4B1" },
  { value: "IMPORT_SERVICES_RCM", label: "Import of Services RCM (Self-Invoiced Sec 5(3))", defaultRow: "4A2" },
  { value: "DOMESTIC_RCM", label: "Domestic Inward Supplies under RCM (Sec 9(3))", defaultRow: "4A3" },
  { value: "RECLAIM_RULE37", label: "Reclaim of Rule 37 previously reversed (Payment Released)", defaultRow: "4D1" },
  { value: "RECLAIM_RULE37A", label: "Reclaim of Rule 37A previously reversed (Supplier Filed 3B)", defaultRow: "4D1" },
  { value: "SEC16_4_INELIGIBLE", label: "Section 16(4) Ineligible Credit (Time-Barred Disclosure)", defaultRow: "4D2" },
  { value: "OTHER_MANUAL", label: "Other Statutory Adjustment", defaultRow: "4A5" },
];

export function Table4AdjustmentModal({
  runId,
  authToken,
  isOpen,
  onClose,
  onSuccess,
}: Table4AdjustmentModalProps) {
  const [category, setCategory] = useState(CATEGORIES[0].value);
  const [rowId, setRowId] = useState(CATEGORIES[0].defaultRow);
  const [adjType, setAdjType] = useState<"ADDITION" | "REDUCTION">("ADDITION");
  const [igst, setIgst] = useState("");
  const [cgst, setCgst] = useState("");
  const [sgst, setSgst] = useState("");
  const [cess, setCess] = useState("");
  const [reason, setReason] = useState("");
  const [refDoc, setRefDoc] = useState("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  if (!isOpen) return null;

  const handleCategoryChange = (val: string) => {
    setCategory(val);
    const found = CATEGORIES.find((c) => c.value === val);
    if (found) setRowId(found.defaultRow);
  };

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!reason || reason.trim().length < 10) {
      setError("Please provide a statutory explanation of at least 10 characters.");
      return;
    }

    setLoading(true);
    setError(null);

    const payload: Table4AdjustmentPayload = {
      row_id: rowId,
      adjustment_type: adjType,
      statutory_category: category,
      igst: parseFloat(igst) || 0,
      cgst: parseFloat(cgst) || 0,
      sgst: parseFloat(sgst) || 0,
      cess: parseFloat(cess) || 0,
      reason: reason.trim(),
      reference_doc: refDoc.trim() || undefined,
    };

    try {
      await gstr3bApi.addTable4Adjustment(authToken, runId, payload);
      onSuccess();
      onClose();
    } catch (err: any) {
      setError(err?.detail || err?.message || "Failed to save adjustment.");
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
              Add Verified External Adjustment
            </h3>
            <p className="mt-0.5 text-[12px] text-gray-500">
              Record external statutory adjustments (Rules 42/43/38, RCM, Reclaims)
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
              Statutory Category
            </label>
            <select
              value={category}
              onChange={(e) => handleCategoryChange(e.target.value)}
              className="w-full rounded-lg border border-[#E5E7EB] px-3 py-2 text-[13px] text-gray-900 bg-white focus:border-black focus:outline-none"
            >
              {CATEGORIES.map((c) => (
                <option key={c.value} value={c.value}>
                  {c.label}
                </option>
              ))}
            </select>
          </div>

          <div className="grid grid-cols-2 gap-3">
            <div>
              <label className="block text-[12px] font-medium text-gray-700 mb-1">
                Target Table 4 Row
              </label>
              <select
                value={rowId}
                onChange={(e) => setRowId(e.target.value)}
                className="w-full rounded-lg border border-[#E5E7EB] px-3 py-2 text-[13px] text-gray-900 bg-white focus:border-black focus:outline-none font-mono font-semibold"
              >
                <option value="4A1">4(A)(1) — Import of Goods</option>
                <option value="4A2">4(A)(2) — Import of Services</option>
                <option value="4A3">4(A)(3) — Inward RCM</option>
                <option value="4A4">4(A)(4) — ISD</option>
                <option value="4A5">4(A)(5) — All other ITC</option>
                <option value="4B1">4(B)(1) — Rules 38, 42, 43 & 17(5)</option>
                <option value="4B2">4(B)(2) — Others (Rule 37, 37A)</option>
                <option value="4D1">4(D)(1) — Reclaimed ITC</option>
                <option value="4D2">4(D)(2) — Ineligible 16(4) & POS</option>
              </select>
            </div>
            <div>
              <label className="block text-[12px] font-medium text-gray-700 mb-1">
                Adjustment Type
              </label>
              <select
                value={adjType}
                onChange={(e) => setAdjType(e.target.value as "ADDITION" | "REDUCTION")}
                className="w-full rounded-lg border border-[#E5E7EB] px-3 py-2 text-[13px] text-gray-900 bg-white focus:border-black focus:outline-none font-semibold"
              >
                <option value="ADDITION">Addition (+)</option>
                <option value="REDUCTION">Reduction (−)</option>
              </select>
            </div>
          </div>

          <div>
            <label className="block text-[12px] font-medium text-gray-700 mb-1">
              Amounts in Rupees (₹)
            </label>
            <div className="grid grid-cols-4 gap-2">
              <div>
                <span className="text-[11px] text-gray-500">IGST</span>
                <input
                  type="number"
                  step="0.01"
                  value={igst}
                  onChange={(e) => setIgst(e.target.value)}
                  placeholder="0.00"
                  className="w-full rounded-lg border border-[#E5E7EB] px-2.5 py-1.5 text-[12px] font-mono focus:border-black focus:outline-none"
                />
              </div>
              <div>
                <span className="text-[11px] text-gray-500">CGST</span>
                <input
                  type="number"
                  step="0.01"
                  value={cgst}
                  onChange={(e) => setCgst(e.target.value)}
                  placeholder="0.00"
                  className="w-full rounded-lg border border-[#E5E7EB] px-2.5 py-1.5 text-[12px] font-mono focus:border-black focus:outline-none"
                />
              </div>
              <div>
                <span className="text-[11px] text-gray-500">SGST</span>
                <input
                  type="number"
                  step="0.01"
                  value={sgst}
                  onChange={(e) => setSgst(e.target.value)}
                  placeholder="0.00"
                  className="w-full rounded-lg border border-[#E5E7EB] px-2.5 py-1.5 text-[12px] font-mono focus:border-black focus:outline-none"
                />
              </div>
              <div>
                <span className="text-[11px] text-gray-500">Cess</span>
                <input
                  type="number"
                  step="0.01"
                  value={cess}
                  onChange={(e) => setCess(e.target.value)}
                  placeholder="0.00"
                  className="w-full rounded-lg border border-[#E5E7EB] px-2.5 py-1.5 text-[12px] font-mono focus:border-black focus:outline-none"
                />
              </div>
            </div>
          </div>

          <div>
            <label className="block text-[12px] font-medium text-gray-700 mb-1">
              Mandatory Statutory Explanation / Basis
            </label>
            <textarea
              rows={2}
              value={reason}
              onChange={(e) => setReason(e.target.value)}
              placeholder="e.g. Reversal on exempt supplies calculation per Rule 42 (Exempt turnover ₹50L vs Total ₹2Cr)..."
              className="w-full rounded-lg border border-[#E5E7EB] px-3 py-2 text-[12px] focus:border-black focus:outline-none"
            />
          </div>

          <div>
            <label className="block text-[12px] font-medium text-gray-700 mb-1">
              Reference Document / JV Number (Optional)
            </label>
            <input
              type="text"
              value={refDoc}
              onChange={(e) => setRefDoc(e.target.value)}
              placeholder="e.g. JV/2026-05/042 or CA Certificate Ref #91"
              className="w-full rounded-lg border border-[#E5E7EB] px-3 py-1.5 text-[12px] focus:border-black focus:outline-none"
            />
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
              {loading ? "Saving…" : "Save Adjustment"}
            </button>
          </div>
        </form>
      </div>
    </div>
  );
}
