"use client";

import { Loader2, X } from "lucide-react";
import { useEffect, useMemo, useState } from "react";

import { AmountDisplay, filterInputClass } from "@/components/reconcile/ResultsUi";
import { formatINR } from "@/lib/format";

const TDS_DISCLAIMER =
  "TDS amount is entered manually by the CA and is not verified by ReconDesk against Income Tax records. Ensure this matches Form 16A or Form 26AS before proceeding.";

export type Rule37MarkPaidTarget = {
  id: string;
  invoice_number: string;
  supplier_gstin: string;
  invoice_amount: number;
};

function parseAmountInput(raw: string): number | null {
  const s = raw.trim().replace(/,/g, "");
  if (!s) return null;
  const n = Number(s);
  if (!Number.isFinite(n) || n < 0) return null;
  return Math.round(n * 100) / 100;
}

export function Rule37MarkPaidModal({
  open,
  row,
  saving,
  onClose,
  onSubmit,
}: {
  open: boolean;
  row: Rule37MarkPaidTarget | null;
  saving: boolean;
  onClose: () => void;
  onSubmit: (payload: {
    amount_paid: number;
    tds_deducted: number;
    tds_confirmed: boolean;
  }) => void | Promise<void>;
}) {
  const [amountPaid, setAmountPaid] = useState("");
  const [tdsDeducted, setTdsDeducted] = useState("");
  const [tdsConfirmed, setTdsConfirmed] = useState(false);

  useEffect(() => {
    if (!open) return;
    setAmountPaid("");
    setTdsDeducted("");
    setTdsConfirmed(false);
  }, [open, row?.id]);

  const paidNum = parseAmountInput(amountPaid);
  const tdsNum = parseAmountInput(tdsDeducted) ?? 0;
  const showTdsExtras = tdsNum > 0;
  const totalSettled =
    paidNum != null ? Math.round((paidNum + tdsNum) * 100) / 100 : null;

  const canSubmit = useMemo(() => {
    if (saving || !row || paidNum == null || paidNum <= 0) return false;
    if (showTdsExtras && !tdsConfirmed) return false;
    return true;
  }, [paidNum, row, saving, showTdsExtras, tdsConfirmed]);

  if (!open || !row) return null;

  return (
    <div
      className="fixed inset-0 z-[100] flex items-center justify-center bg-black/40 p-4"
      role="dialog"
      aria-modal="true"
      aria-labelledby="rule37-mark-paid-title"
    >
      <div className="flex w-full max-w-md flex-col overflow-hidden rounded-2xl border border-[#F0F0F0] bg-white shadow-xl">
        <div className="flex items-center justify-between border-b border-[#F0F0F0] px-5 py-4">
          <h2
            id="rule37-mark-paid-title"
            className="text-lg font-semibold text-gray-900"
          >
            Mark Paid
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
            <p className="font-medium text-gray-900">{row.invoice_number}</p>
            <p className="font-mono text-[12px] text-gray-500">
              {row.supplier_gstin}
            </p>
            <p className="mt-2 text-[12px] text-gray-500">
              Invoice amount:{" "}
              <AmountDisplay amount={row.invoice_amount} />
            </p>
          </div>

          <div>
            <label
              htmlFor="rule37-amount-paid"
              className="mb-1 block text-[11px] font-medium uppercase tracking-wide text-gray-500"
            >
              Amount Paid
            </label>
            <input
              id="rule37-amount-paid"
              type="text"
              inputMode="decimal"
              value={amountPaid}
              onChange={(e) => setAmountPaid(e.target.value)}
              placeholder="Enter cash payment amount"
              className={`${filterInputClass} w-full`}
              disabled={saving}
            />
          </div>

          <div>
            <label
              htmlFor="rule37-tds-deducted"
              className="mb-1 block text-[11px] font-medium uppercase tracking-wide text-gray-500"
            >
              TDS Deducted (optional)
            </label>
            <input
              id="rule37-tds-deducted"
              type="text"
              inputMode="decimal"
              value={tdsDeducted}
              onChange={(e) => {
                setTdsDeducted(e.target.value);
                if (!parseAmountInput(e.target.value)) {
                  setTdsConfirmed(false);
                }
              }}
              placeholder="0"
              className={`${filterInputClass} w-full`}
              disabled={saving}
            />
          </div>

          {showTdsExtras && totalSettled != null ? (
            <div className="space-y-3 rounded-xl border border-[#F0F0F0] bg-[#FAFAFA] px-4 py-3">
              <p className="text-[13px] font-semibold text-gray-900">
                Total Settled: {formatINR(totalSettled)}
              </p>
              <label className="flex cursor-pointer items-start gap-2 text-[13px] text-gray-700">
                <input
                  type="checkbox"
                  checked={tdsConfirmed}
                  onChange={(e) => setTdsConfirmed(e.target.checked)}
                  disabled={saving}
                  className="mt-0.5 h-4 w-4 rounded border-gray-300 accent-brand focus:ring-brand/30"
                />
                <span>
                  I confirm this TDS amount is verified against Form 16A /
                  Form 26AS
                </span>
              </label>
              <p className="text-[11px] italic text-gray-500">{TDS_DISCLAIMER}</p>
            </div>
          ) : null}
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
              if (paidNum == null) return;
              void onSubmit({
                amount_paid: paidNum,
                tds_deducted: tdsNum,
                tds_confirmed: showTdsExtras ? tdsConfirmed : false,
              });
            }}
            className="rounded-xl bg-brand px-4 py-2 text-[13px] font-semibold text-white hover:bg-brand-hover disabled:cursor-not-allowed disabled:opacity-50"
          >
            Mark Paid
          </button>
        </div>
      </div>
    </div>
  );
}
