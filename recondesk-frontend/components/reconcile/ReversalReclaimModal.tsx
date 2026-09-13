"use client";

import { useEffect, useState } from "react";
import {
  reversalLedgerApi,
  type ReversalLedgerEntryDto,
  type ReclaimExecutionResponse,
} from "@/lib/api";
import { formatINR } from "@/lib/format";
import {
  STATUTORY_REASON_LABELS,
  generateReclaimIdempotencyKey,
  paiseToRupees,
  rupeesToPaise,
  validateReclaimAmounts,
  type TaxHeadPaise,
} from "./reversalLedgerLogic";

interface ActiveRunOption {
  id: string;
  period: string;
  is_locked: boolean;
  status: string;
}

interface ReversalReclaimModalProps {
  isOpen: boolean;
  onClose: () => void;
  onSuccess: (result: ReclaimExecutionResponse) => void;
  entry: ReversalLedgerEntryDto | null;
  targetRuns: ActiveRunOption[];
  defaultTargetRunId?: string;
  authToken: string;
}

export function ReversalReclaimModal({
  isOpen,
  onClose,
  onSuccess,
  entry,
  targetRuns,
  defaultTargetRunId,
  authToken,
}: ReversalReclaimModalProps) {
  const [selectedTargetRunId, setSelectedTargetRunId] = useState<string>("");
  const [igstInput, setIgstInput] = useState<string>("");
  const [cgstInput, setCgstInput] = useState<string>("");
  const [sgstInput, setSgstInput] = useState<string>("");
  const [cessInput, setCessInput] = useState<string>("");
  const [reclaimNotes, setReclaimNotes] = useState<string>("");

  const [step, setStep] = useState<"form" | "confirm">("form");
  const [isSubmitting, setIsSubmitting] = useState<boolean>(false);
  const [errorMessage, setErrorMessage] = useState<string | null>(null);

  // Available balances from entry
  const rem = entry?.remaining_balances_paise;
  const bal = rem
    ? {
        igst_paise: rem.igst,
        cgst_paise: rem.cgst,
        sgst_paise: rem.sgst,
        cess_paise: rem.cess,
        total_tax_paise: rem.total,
      }
    : entry?.available_balance_paise || {
        igst_paise:
          (entry?.reversed_igst_paise || 0) -
          (entry?.cached_reclaimed_igst_paise ?? entry?.reclaimed_igst_paise ?? 0),
        cgst_paise:
          (entry?.reversed_cgst_paise || 0) -
          (entry?.cached_reclaimed_cgst_paise ?? entry?.reclaimed_cgst_paise ?? 0),
        sgst_paise:
          (entry?.reversed_sgst_paise || 0) -
          (entry?.cached_reclaimed_sgst_paise ?? entry?.reclaimed_sgst_paise ?? 0),
        cess_paise:
          (entry?.reversed_cess_paise || 0) -
          (entry?.cached_reclaimed_cess_paise ?? entry?.reclaimed_cess_paise ?? 0),
        total_tax_paise:
          ((entry?.reversed_igst_paise || 0) +
            (entry?.reversed_cgst_paise || 0) +
            (entry?.reversed_sgst_paise || 0) +
            (entry?.reversed_cess_paise || 0)) -
          ((entry?.cached_reclaimed_igst_paise ?? entry?.reclaimed_igst_paise ?? 0) +
            (entry?.cached_reclaimed_cgst_paise ?? entry?.reclaimed_cgst_paise ?? 0) +
            (entry?.cached_reclaimed_sgst_paise ?? entry?.reclaimed_sgst_paise ?? 0) +
            (entry?.cached_reclaimed_cess_paise ?? entry?.reclaimed_cess_paise ?? 0)),
      };

  const availablePaise: TaxHeadPaise = {
    igst_paise: Math.max(0, bal.igst_paise),
    cgst_paise: Math.max(0, bal.cgst_paise),
    sgst_paise: Math.max(0, bal.sgst_paise),
    cess_paise: Math.max(0, bal.cess_paise),
  };

  // Prepopulate on open
  useEffect(() => {
    if (isOpen && entry) {
      setStep("form");
      setErrorMessage(null);
      setReclaimNotes("");

      // Default target run
      const activeRuns = targetRuns.filter(
        (r) => !r.is_locked && r.status?.toUpperCase() !== "FINAL"
      );
      if (defaultTargetRunId && activeRuns.some((r) => r.id === defaultTargetRunId)) {
        setSelectedTargetRunId(defaultTargetRunId);
      } else if (activeRuns.length > 0) {
        setSelectedTargetRunId(activeRuns[0].id);
      } else {
        setSelectedTargetRunId("");
      }

      // Default to available balances in Rupees
      setIgstInput(availablePaise.igst_paise > 0 ? String(paiseToRupees(availablePaise.igst_paise)) : "0");
      setCgstInput(availablePaise.cgst_paise > 0 ? String(paiseToRupees(availablePaise.cgst_paise)) : "0");
      setSgstInput(availablePaise.sgst_paise > 0 ? String(paiseToRupees(availablePaise.sgst_paise)) : "0");
      setCessInput(availablePaise.cess_paise > 0 ? String(paiseToRupees(availablePaise.cess_paise)) : "0");
    }
  }, [isOpen, entry, defaultTargetRunId, targetRuns]);

  if (!isOpen || !entry) return null;

  const activeRuns = targetRuns.filter(
    (r) => !r.is_locked && r.status?.toUpperCase() !== "FINAL"
  );
  const currentTargetRun = targetRuns.find((r) => r.id === selectedTargetRunId);

  const requestedPaise: TaxHeadPaise = {
    igst_paise: rupeesToPaise(igstInput),
    cgst_paise: rupeesToPaise(cgstInput),
    sgst_paise: rupeesToPaise(sgstInput),
    cess_paise: rupeesToPaise(cessInput),
  };

  const totalRequestedPaise =
    requestedPaise.igst_paise +
    requestedPaise.cgst_paise +
    requestedPaise.sgst_paise +
    requestedPaise.cess_paise;

  const handleProceedToConfirm = (e: React.FormEvent) => {
    e.preventDefault();
    setErrorMessage(null);

    if (!selectedTargetRunId) {
      setErrorMessage("Please select an active target return run.");
      return;
    }

    const validation = validateReclaimAmounts(requestedPaise, availablePaise);
    if (!validation.isValid) {
      setErrorMessage(validation.errorMessage || "Invalid reclaim amounts.");
      return;
    }

    setStep("confirm");
  };

  const handleExecuteReclaim = async () => {
    if (!entry || !selectedTargetRunId) return;
    setIsSubmitting(true);
    setErrorMessage(null);

    const idempotencyKey = generateReclaimIdempotencyKey(entry.id, selectedTargetRunId);

    try {
      const res = await reversalLedgerApi.executeReclaim(
        authToken,
        selectedTargetRunId,
        {
          ledger_id: entry.id,
          reclaim_igst_paise: requestedPaise.igst_paise,
          reclaim_cgst_paise: requestedPaise.cgst_paise,
          reclaim_sgst_paise: requestedPaise.sgst_paise,
          reclaim_cess_paise: requestedPaise.cess_paise,
          reclaim_notes: reclaimNotes.trim() || undefined,
          idempotency_key: idempotencyKey,
        }
      );
      onSuccess(res);
      onClose();
    } catch (err: any) {
      setErrorMessage(
        err?.detail || err?.message || "Failed to execute reclaim into target return."
      );
      setStep("form");
    } finally {
      setIsSubmitting(false);
    }
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 backdrop-blur-sm p-4">
      <div className="w-full max-w-xl rounded-2xl border border-[#E5E7EB] bg-white p-6 shadow-2xl animate-in fade-in zoom-in-95 duration-150">
        {/* Header */}
        <div className="flex items-start justify-between border-b border-[#E5E7EB] pb-4">
          <div>
            <span className="inline-flex items-center gap-1 rounded bg-black px-2 py-0.5 text-[11px] font-bold text-white uppercase tracking-wider">
              Reclaim Execution
            </span>
            <h2 className="mt-1 text-[17px] font-bold text-gray-900">
              Execute ITC Reclaim into Active GSTR-3B
            </h2>
            <p className="mt-0.5 text-[12px] text-gray-500">
              Claim authorized reversal into Table 4(A)(5) and Form 4(D)(1) of the selected tax period.
            </p>
          </div>
          <button
            onClick={onClose}
            className="rounded-lg p-1.5 text-gray-400 hover:bg-gray-100 hover:text-gray-700"
          >
            ✕
          </button>
        </div>

        {errorMessage && (
          <div className="mt-3 rounded-xl border border-red-200 bg-red-50 p-3 text-[12.5px] text-red-800">
            {errorMessage}
          </div>
        )}

        {step === "form" ? (
          <form onSubmit={handleProceedToConfirm} className="mt-4 space-y-4">
            {/* Source Reversal Info */}
            <div className="rounded-xl border border-gray-200 bg-gray-50/70 p-3.5 text-[12.5px] space-y-1">
              <div className="flex justify-between">
                <span className="text-gray-500">Source Document:</span>
                <span className="font-semibold text-gray-900 font-mono">
                  {entry.document_number} ({entry.supplier_gstin})
                </span>
              </div>
              <div className="flex justify-between">
                <span className="text-gray-500">Source Reversal Period:</span>
                <span className="font-medium text-gray-900">{entry.reversal_tax_period}</span>
              </div>
              <div className="flex justify-between">
                <span className="text-gray-500">Statutory Reason:</span>
                <span className="font-medium text-gray-900">
                  {STATUTORY_REASON_LABELS[entry.statutory_reason] || entry.statutory_reason}
                </span>
              </div>
            </div>

            {/* Target Run Selector */}
            <div>
              <label className="block text-[12px] font-semibold text-gray-700 mb-1">
                Target Return Period (Active Run) <span className="text-red-500">*</span>
              </label>
              {activeRuns.length === 0 ? (
                <div className="rounded-lg border border-amber-200 bg-amber-50 p-3 text-[12px] text-amber-800">
                  No active (unlocked) reconciliation runs found for this client. Create or open an active run to execute a reclaim.
                </div>
              ) : (
                <select
                  value={selectedTargetRunId}
                  onChange={(e) => setSelectedTargetRunId(e.target.value)}
                  className="w-full rounded-lg border border-gray-300 px-3 py-2 text-[13px] text-gray-900 focus:border-black focus:outline-none focus:ring-1 focus:ring-black bg-white"
                >
                  {activeRuns.map((r) => (
                    <option key={r.id} value={r.id}>
                      Tax Period {r.period} (Run ID: {r.id.substring(0, 8)}…)
                    </option>
                  ))}
                </select>
              )}
            </div>

            {/* Available vs Requested Amounts Grid */}
            <div className="rounded-xl border border-[#E5E7EB] bg-white overflow-hidden">
              <div className="bg-[#F8FAFC] px-4 py-2 border-b border-[#E5E7EB] flex justify-between items-center text-[11px] font-bold text-gray-600 uppercase tracking-wider">
                <span>Tax Head</span>
                <span>Available Balance</span>
                <span>Reclaim Amount (₹)</span>
              </div>
              <div className="divide-y divide-gray-100 text-[13px]">
                {/* IGST */}
                <div className="px-4 py-2.5 flex items-center justify-between gap-3">
                  <span className="font-semibold text-gray-900 w-20">IGST</span>
                  <span className="font-mono text-gray-600 tabular-nums">
                    {formatINR(paiseToRupees(availablePaise.igst_paise))}
                  </span>
                  <div className="flex items-center gap-1.5">
                    <input
                      type="number"
                      step="0.01"
                      min="0"
                      value={igstInput}
                      onChange={(e) => setIgstInput(e.target.value)}
                      className="w-32 rounded border border-gray-300 px-2 py-1 text-right font-mono text-[13px] focus:border-black focus:outline-none"
                    />
                    <button
                      type="button"
                      onClick={() => setIgstInput(String(paiseToRupees(availablePaise.igst_paise)))}
                      className="text-[10.5px] font-semibold text-gray-500 hover:text-black uppercase px-1 py-0.5 border rounded hover:bg-gray-50"
                    >
                      Max
                    </button>
                  </div>
                </div>

                {/* CGST */}
                <div className="px-4 py-2.5 flex items-center justify-between gap-3">
                  <span className="font-semibold text-gray-900 w-20">CGST</span>
                  <span className="font-mono text-gray-600 tabular-nums">
                    {formatINR(paiseToRupees(availablePaise.cgst_paise))}
                  </span>
                  <div className="flex items-center gap-1.5">
                    <input
                      type="number"
                      step="0.01"
                      min="0"
                      value={cgstInput}
                      onChange={(e) => setCgstInput(e.target.value)}
                      className="w-32 rounded border border-gray-300 px-2 py-1 text-right font-mono text-[13px] focus:border-black focus:outline-none"
                    />
                    <button
                      type="button"
                      onClick={() => setCgstInput(String(paiseToRupees(availablePaise.cgst_paise)))}
                      className="text-[10.5px] font-semibold text-gray-500 hover:text-black uppercase px-1 py-0.5 border rounded hover:bg-gray-50"
                    >
                      Max
                    </button>
                  </div>
                </div>

                {/* SGST */}
                <div className="px-4 py-2.5 flex items-center justify-between gap-3">
                  <span className="font-semibold text-gray-900 w-20">SGST</span>
                  <span className="font-mono text-gray-600 tabular-nums">
                    {formatINR(paiseToRupees(availablePaise.sgst_paise))}
                  </span>
                  <div className="flex items-center gap-1.5">
                    <input
                      type="number"
                      step="0.01"
                      min="0"
                      value={sgstInput}
                      onChange={(e) => setSgstInput(e.target.value)}
                      className="w-32 rounded border border-gray-300 px-2 py-1 text-right font-mono text-[13px] focus:border-black focus:outline-none"
                    />
                    <button
                      type="button"
                      onClick={() => setSgstInput(String(paiseToRupees(availablePaise.sgst_paise)))}
                      className="text-[10.5px] font-semibold text-gray-500 hover:text-black uppercase px-1 py-0.5 border rounded hover:bg-gray-50"
                    >
                      Max
                    </button>
                  </div>
                </div>

                {/* Cess */}
                <div className="px-4 py-2.5 flex items-center justify-between gap-3">
                  <span className="font-semibold text-gray-900 w-20">Cess</span>
                  <span className="font-mono text-gray-600 tabular-nums">
                    {formatINR(paiseToRupees(availablePaise.cess_paise))}
                  </span>
                  <div className="flex items-center gap-1.5">
                    <input
                      type="number"
                      step="0.01"
                      min="0"
                      value={cessInput}
                      onChange={(e) => setCessInput(e.target.value)}
                      className="w-32 rounded border border-gray-300 px-2 py-1 text-right font-mono text-[13px] focus:border-black focus:outline-none"
                    />
                    <button
                      type="button"
                      onClick={() => setCessInput(String(paiseToRupees(availablePaise.cess_paise)))}
                      className="text-[10.5px] font-semibold text-gray-500 hover:text-black uppercase px-1 py-0.5 border rounded hover:bg-gray-50"
                    >
                      Max
                    </button>
                  </div>
                </div>
              </div>

              {/* Total Requested Footer */}
              <div className="bg-gray-50 px-4 py-2.5 border-t border-[#E5E7EB] flex justify-between items-center text-[13px] font-bold">
                <span className="text-gray-700">Total Requested Reclaim:</span>
                <span className="font-mono text-gray-900 tabular-nums text-[14px]">
                  {formatINR(paiseToRupees(totalRequestedPaise))}
                </span>
              </div>
            </div>

            <div>
              <label className="block text-[12px] font-semibold text-gray-700 mb-1">
                Reclaim Audit Notes (Optional)
              </label>
              <input
                type="text"
                placeholder="Optional explanation for this period's reclaim entry…"
                value={reclaimNotes}
                onChange={(e) => setReclaimNotes(e.target.value)}
                className="w-full rounded-lg border border-gray-300 px-3 py-2 text-[13px] text-gray-900 focus:border-black focus:outline-none focus:ring-1 focus:ring-black"
              />
            </div>

            <div className="flex items-center justify-end gap-2 border-t border-[#E5E7EB] pt-4">
              <button
                type="button"
                onClick={onClose}
                className="rounded-lg border border-gray-300 bg-white px-4 py-2 text-[12.5px] font-semibold text-gray-700 hover:bg-gray-50 transition"
              >
                Cancel
              </button>
              <button
                type="submit"
                disabled={activeRuns.length === 0 || totalRequestedPaise <= 0}
                className="inline-flex items-center gap-1.5 rounded-lg bg-black px-4 py-2 text-[12.5px] font-semibold text-white hover:bg-gray-800 transition disabled:opacity-50"
              >
                Review Reclaim Summary →
              </button>
            </div>
          </form>
        ) : (
          /* Step 2: Confirmation Summary Screen */
          <div className="mt-4 space-y-4">
            <div className="rounded-xl border border-emerald-200 bg-emerald-50/50 p-4 space-y-2 text-[13px]">
              <h4 className="font-bold text-emerald-950 uppercase tracking-wider text-[11px] flex items-center gap-1.5">
                <span className="h-2 w-2 rounded-full bg-emerald-600" />
                Statutory Reclaim Confirmation Summary
              </h4>

              <div className="space-y-1 text-gray-700">
                <p>
                  <span className="font-medium text-gray-900">Source Reversal:</span>{" "}
                  {entry.reversal_tax_period} • {STATUTORY_REASON_LABELS[entry.statutory_reason] || entry.statutory_reason}
                </p>
                <p>
                  <span className="font-medium text-gray-900">Available:</span> IGST ₹{paiseToRupees(availablePaise.igst_paise)}, CGST ₹{paiseToRupees(availablePaise.cgst_paise)}, SGST ₹{paiseToRupees(availablePaise.sgst_paise)}, Cess ₹{paiseToRupees(availablePaise.cess_paise)}
                </p>
                <div className="border-t border-emerald-200 pt-1.5">
                  <p>
                    <span className="font-medium text-gray-900">Reclaiming Into:</span>{" "}
                    <span className="font-bold text-black font-mono">Tax Period {currentTargetRun?.period || "—"}</span>
                  </p>
                  <p>
                    <span className="font-medium text-gray-900">Requested Reclaim:</span>{" "}
                    <span className="font-bold text-emerald-900">
                      IGST ₹{paiseToRupees(requestedPaise.igst_paise)}, CGST ₹{paiseToRupees(requestedPaise.cgst_paise)}, SGST ₹{paiseToRupees(requestedPaise.sgst_paise)}, Cess ₹{paiseToRupees(requestedPaise.cess_paise)}
                    </span>
                  </p>
                </div>
                <div className="border-t border-emerald-200 pt-1.5 text-[12px] font-semibold text-emerald-950">
                  Resulting Table 4 Effect: Dual posting to Table 4(A)(5) (Eligible ITC) and Table 4(D)(1) (Reclaimed ITC).
                </div>
              </div>
            </div>

            <p className="text-[11.5px] italic text-gray-500">
              Note: Execution is atomic and verified against the backend database unique constraint. The target return will be credited immediately.
            </p>

            <div className="flex items-center justify-end gap-2 border-t border-[#E5E7EB] pt-4">
              <button
                type="button"
                onClick={() => setStep("form")}
                disabled={isSubmitting}
                className="rounded-lg border border-gray-300 bg-white px-4 py-2 text-[12.5px] font-semibold text-gray-700 hover:bg-gray-50 transition"
              >
                ← Back to Edit
              </button>
              <button
                type="button"
                onClick={handleExecuteReclaim}
                disabled={isSubmitting}
                className="inline-flex items-center gap-1.5 rounded-lg bg-emerald-800 px-5 py-2 text-[12.5px] font-semibold text-white hover:bg-emerald-900 transition disabled:opacity-50"
              >
                {isSubmitting ? (
                  <>
                    <svg className="h-3.5 w-3.5 animate-spin" fill="none" viewBox="0 0 24 24">
                      <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
                      <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8v8z" />
                    </svg>
                    Executing Reclaim…
                  </>
                ) : (
                  "Confirm & Execute Reclaim"
                )}
              </button>
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
