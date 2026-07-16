"use client";

import { Loader2, X } from "lucide-react";
import { useEffect, useMemo, useState } from "react";

import { filterInputClass } from "@/components/reconcile/ResultsUi";

const FILED_CAUTION =
  "Marking GSTR-1A as filed records that amendments for this period have been submitted on the GST portal. This removes the period from the open GSTR-1A queue.";

export type Gstr1aMarkFiledTarget = {
  period: string;
  mismatchCount: number;
};

export function Gstr1aMarkFiledModal({
  open,
  target,
  saving,
  onClose,
  onSubmit,
}: {
  open: boolean;
  target: Gstr1aMarkFiledTarget | null;
  saving: boolean;
  onClose: () => void;
  onSubmit: (payload: {
    confirmed: boolean;
    filed_date?: string;
    note?: string;
  }) => void | Promise<void>;
}) {
  const [filedDate, setFiledDate] = useState("");
  const [note, setNote] = useState("");
  const [confirmed, setConfirmed] = useState(false);

  useEffect(() => {
    if (!open) return;
    setFiledDate(new Date().toISOString().slice(0, 10));
    setNote("");
    setConfirmed(false);
  }, [open, target?.period]);

  const canSubmit = useMemo(() => {
    if (saving || !target || !confirmed) return false;
    return true;
  }, [confirmed, saving, target]);

  if (!open || !target) return null;

  return (
    <div
      className="fixed inset-0 z-[100] flex items-center justify-center bg-black/40 p-4"
      role="dialog"
      aria-modal="true"
      aria-labelledby="gstr1a-mark-filed-title"
    >
      <div className="flex w-full max-w-md flex-col overflow-hidden rounded-2xl border border-[#F0F0F0] bg-white shadow-xl">
        <div className="flex items-center justify-between border-b border-[#F0F0F0] px-5 py-4">
          <h2
            id="gstr1a-mark-filed-title"
            className="text-lg font-semibold text-gray-900"
          >
            Mark GSTR-1A as filed
          </h2>
          <button
            type="button"
            onClick={onClose}
            disabled={saving}
            className="rounded-lg p-1 text-gray-500 hover:bg-gray-100 disabled:opacity-50"
            aria-label="Close"
          >
            <X className="h-5 w-5" />
          </button>
        </div>

        <div className="space-y-4 px-5 py-4">
          <div className="text-[13px] text-gray-600">
            <p className="font-medium text-gray-900">Period {target.period}</p>
            <p className="text-[12px] text-gray-500">
              {target.mismatchCount.toLocaleString("en-IN")} eligible mismatch
              {target.mismatchCount === 1 ? "" : "es"}
            </p>
          </div>

          <div>
            <label
              htmlFor="gstr1a-filed-date"
              className="mb-1 block text-[11px] font-medium uppercase tracking-wide text-gray-500"
            >
              Filed date
            </label>
            <input
              id="gstr1a-filed-date"
              type="date"
              value={filedDate}
              onChange={(e) => setFiledDate(e.target.value)}
              className={`${filterInputClass} w-full`}
              disabled={saving}
            />
          </div>

          <div>
            <label
              htmlFor="gstr1a-filed-note"
              className="mb-1 block text-[11px] font-medium uppercase tracking-wide text-gray-500"
            >
              Note (optional)
            </label>
            <input
              id="gstr1a-filed-note"
              type="text"
              value={note}
              onChange={(e) => setNote(e.target.value)}
              placeholder="e.g. Filed on GST portal ARN …"
              className={`${filterInputClass} w-full`}
              disabled={saving}
            />
          </div>

          <div className="space-y-3 rounded-xl border border-[#F0F0F0] bg-[#FAFAFA] px-4 py-3">
            <label className="flex cursor-pointer items-start gap-2 text-[13px] text-gray-700">
              <input
                type="checkbox"
                checked={confirmed}
                onChange={(e) => setConfirmed(e.target.checked)}
                disabled={saving}
                className="mt-0.5 h-4 w-4 rounded border-gray-300 accent-[var(--ink)] focus:ring-black/20"
              />
              <span>
                I confirm GSTR-1A for period {target.period} has been filed on
                the GST portal.
              </span>
            </label>
            <p className="text-[11px] italic text-gray-500">{FILED_CAUTION}</p>
          </div>
        </div>

        <div className="flex items-center justify-end gap-2 border-t border-[#F0F0F0] px-5 py-4">
          {saving ? (
            <span className="mr-auto inline-flex items-center gap-1 text-[12px] text-gray-500">
              <Loader2 className="h-3 w-3 animate-spin" />
              Saving…
            </span>
          ) : null}
          <button
            type="button"
            onClick={onClose}
            disabled={saving}
            className="rounded-xl border border-[#E5E7EB] bg-white px-4 py-2 text-[13px] font-medium text-gray-700 hover:bg-gray-50 disabled:opacity-50"
          >
            Cancel
          </button>
          <button
            type="button"
            disabled={!canSubmit}
            onClick={() => {
              void onSubmit({
                confirmed: true,
                filed_date: filedDate.trim() || undefined,
                note: note.trim() || undefined,
              });
            }}
            className="rounded-xl bg-[var(--ink)] px-4 py-2 text-[13px] font-semibold text-white hover:opacity-90 disabled:cursor-not-allowed disabled:opacity-50"
          >
            Mark as filed
          </button>
        </div>
      </div>
    </div>
  );
}
