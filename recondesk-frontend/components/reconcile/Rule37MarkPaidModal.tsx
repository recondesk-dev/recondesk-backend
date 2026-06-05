"use client";

import { Loader2, X } from "lucide-react";
import { useEffect, useMemo, useState } from "react";

import { filterInputClass } from "@/components/reconcile/ResultsUi";
import { formatINR } from "@/lib/format";

const SETTLEMENT_CAUTION =
  "TDS/statutory deduction is entered manually and is not verified by ReconDesk. CA/client should verify payment records, TDS challan/return, Form 16A, Form 26AS, or applicable GST TDS records before proceeding.";

const SETTLEMENT_EXCEEDS_WARNING =
  "Settlement exceeds invoice amount. Check whether the paid amount is net of TDS/statutory deduction.";

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

function SettlementLine({
  label,
  amount,
  bold,
  warn,
}: {
  label: string;
  amount: number;
  bold?: boolean;
  warn?: boolean;
}) {
  return (
    <div className="flex items-center justify-between gap-3 text-[13px]">
      <span className="text-gray-600">{label}</span>
      <span
        className={
          warn
            ? "font-semibold text-red-600"
            : bold
              ? "font-semibold text-gray-900"
              : "text-gray-800"
        }
      >
        {formatINR(amount)}
      </span>
    </div>
  );
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
  const [netPaid, setNetPaid] = useState("");
  const [statutoryDeduction, setStatutoryDeduction] = useState("");
  const [settlementConfirmed, setSettlementConfirmed] = useState(false);

  useEffect(() => {
    if (!open) return;
    setNetPaid("");
    setStatutoryDeduction("");
    setSettlementConfirmed(false);
  }, [open, row?.id]);

  const netPaidNum = parseAmountInput(netPaid);
  const statutoryNum = parseAmountInput(statutoryDeduction) ?? 0;
  const showSettlementSummary = netPaidNum != null && netPaidNum > 0;
  const settlementConsidered =
    netPaidNum != null
      ? Math.round((netPaidNum + statutoryNum) * 100) / 100
      : null;
  const remainingUnpaid =
    row && settlementConsidered != null
      ? Math.round(Math.max(row.invoice_amount - settlementConsidered, 0) * 100) /
        100
      : null;
  const settlementExceeds =
    row != null &&
    settlementConsidered != null &&
    row.invoice_amount > 0 &&
    settlementConsidered > row.invoice_amount + 0.005;

  const canSubmit = useMemo(() => {
    if (saving || !row || netPaidNum == null || netPaidNum <= 0) return false;
    if (settlementExceeds) return false;
    if (!settlementConfirmed) return false;
    return true;
  }, [netPaidNum, row, saving, settlementConfirmed, settlementExceeds]);

  if (!open || !row) return null;

  return (
    <div
      className="fixed inset-0 z-[100] flex items-center justify-center bg-black/40 p-4"
      role="dialog"
      aria-modal="true"
      aria-labelledby="rule37-mark-settled-title"
    >
      <div className="flex w-full max-w-md flex-col overflow-hidden rounded-2xl border border-[#F0F0F0] bg-white shadow-xl">
        <div className="flex items-center justify-between border-b border-[#F0F0F0] px-5 py-4">
          <h2
            id="rule37-mark-settled-title"
            className="text-lg font-semibold text-gray-900"
          >
            Mark as Settled
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
          </div>

          <div>
            <label
              htmlFor="rule37-net-paid"
              className="mb-1 block text-[11px] font-medium uppercase tracking-wide text-gray-500"
            >
              Net Paid to Supplier
            </label>
            <input
              id="rule37-net-paid"
              type="text"
              inputMode="decimal"
              value={netPaid}
              onChange={(e) => {
                setNetPaid(e.target.value);
                setSettlementConfirmed(false);
              }}
              placeholder="Enter net cash paid to supplier"
              className={`${filterInputClass} w-full`}
              disabled={saving}
            />
          </div>

          <div>
            <label
              htmlFor="rule37-statutory-deduction"
              className="mb-1 block text-[11px] font-medium uppercase tracking-wide text-gray-500"
            >
              TDS / Statutory Deduction (Optional)
            </label>
            <input
              id="rule37-statutory-deduction"
              type="text"
              inputMode="decimal"
              value={statutoryDeduction}
              onChange={(e) => {
                setStatutoryDeduction(e.target.value);
                setSettlementConfirmed(false);
              }}
              placeholder="0"
              className={`${filterInputClass} w-full`}
              disabled={saving}
            />
          </div>

          {showSettlementSummary &&
          settlementConsidered != null &&
          remainingUnpaid != null ? (
            <div className="space-y-3 rounded-xl border border-[#F0F0F0] bg-[#FAFAFA] px-4 py-3">
              <SettlementLine
                label="Invoice Amount"
                amount={row.invoice_amount}
              />
              <SettlementLine label="Net Paid to Supplier" amount={netPaidNum} />
              <SettlementLine
                label="TDS / Statutory Deduction"
                amount={statutoryNum}
              />
              <SettlementLine
                label="Settlement Considered for Rule 37"
                amount={settlementConsidered}
                bold
              />
              <SettlementLine
                label="Remaining Unpaid for Rule 37"
                amount={remainingUnpaid}
                warn={remainingUnpaid > 0}
              />

              {settlementExceeds ? (
                <p className="rounded-lg border border-red-200 bg-red-50 px-3 py-2 text-[12px] font-medium text-red-700">
                  {SETTLEMENT_EXCEEDS_WARNING}
                </p>
              ) : null}

              <label className="flex cursor-pointer items-start gap-2 text-[13px] text-gray-700">
                <input
                  type="checkbox"
                  checked={settlementConfirmed}
                  onChange={(e) => setSettlementConfirmed(e.target.checked)}
                  disabled={saving || settlementExceeds}
                  className="mt-0.5 h-4 w-4 rounded border-gray-300 accent-brand focus:ring-brand/30"
                />
                <span>
                  I confirm this settlement has been verified against payment
                  records / TDS records before marking this invoice as settled.
                </span>
              </label>
              <p className="text-[11px] italic text-gray-500">
                {SETTLEMENT_CAUTION}
              </p>
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
              if (netPaidNum == null) return;
              void onSubmit({
                amount_paid: netPaidNum,
                tds_deducted: statutoryNum,
                tds_confirmed: settlementConfirmed,
              });
            }}
            className="rounded-xl bg-brand px-4 py-2 text-[13px] font-semibold text-white hover:bg-brand-hover disabled:cursor-not-allowed disabled:opacity-50"
          >
            Mark as Settled
          </button>
        </div>
      </div>
    </div>
  );
}
