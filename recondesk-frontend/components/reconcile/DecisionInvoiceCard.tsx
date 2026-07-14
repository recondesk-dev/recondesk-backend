"use client";

import type { ReactNode } from "react";

import { AmountDisplay } from "@/components/reconcile/ResultsUi";
import { GstinCell } from "@/components/ui/GstinCell";

function DecisionField({
  label,
  value,
  tone = "default",
}: {
  label: string;
  value: string | null | undefined;
  tone?: "default" | "muted" | "action";
}) {
  const text = value?.trim() || "—";
  const toneClass =
    tone === "action"
      ? "font-medium text-[var(--ink)]"
      : tone === "muted"
        ? "text-gray-500"
        : "text-gray-700";

  return (
    <div className="min-w-0 rounded-xl bg-[#F7F7F8] px-3.5 py-3">
      <p className="text-[10px] font-semibold uppercase tracking-widest text-gray-400">
        {label}
      </p>
      <p className={`mt-1.5 text-[13px] leading-relaxed ${toneClass}`}>{text}</p>
    </div>
  );
}

export function DecisionInvoiceCard({
  index,
  gstin,
  invoiceNumber,
  invoiceDate,
  amount,
  amountCaption = "Amount",
  selected = false,
  onSelectChange,
  checkboxDisabled = false,
  impact,
  status,
  trailing,
  meta,
  what,
  why,
  next,
  expandedContent,
  onOpen,
}: {
  index: number;
  gstin: string;
  invoiceNumber: string;
  invoiceDate: string;
  amount: number;
  amountCaption?: string;
  selected?: boolean;
  onSelectChange?: (checked: boolean) => void;
  checkboxDisabled?: boolean;
  impact?: ReactNode;
  status?: ReactNode;
  trailing?: ReactNode;
  meta?: ReactNode;
  what: string | null | undefined;
  why: string | null | undefined;
  next: string | null | undefined;
  expandedContent?: ReactNode;
  onOpen?: () => void;
}) {
  const selectable = typeof onSelectChange === "function";

  return (
    <article
      className={`rounded-[1.25rem] bg-white shadow-[var(--shadow-soft)] ring-1 ring-[#F0F0F0] transition-shadow ${
        selected ? "ring-2 ring-[var(--ink)]/15" : "hover:shadow-[var(--shadow-lift)]"
      }`}
    >
      <div className="flex flex-col gap-4 p-4 sm:p-5">
        {/* Identity row */}
        <div className="flex flex-wrap items-start gap-3">
          <div className="mt-1 flex shrink-0 items-center gap-2">
            {selectable ? (
              <input
                type="checkbox"
                disabled={checkboxDisabled}
                checked={selected}
                onChange={(e) => onSelectChange?.(e.target.checked)}
                onClick={(e) => e.stopPropagation()}
                className="rounded border-gray-300"
                aria-label={`Select invoice ${invoiceNumber}`}
              />
            ) : null}
            <span className="w-6 text-[12px] tabular-nums text-gray-400">#{index}</span>
          </div>

          <div
            className={`min-w-0 flex-1 ${onOpen ? "cursor-pointer" : ""}`}
            onClick={onOpen}
            onKeyDown={
              onOpen
                ? (e) => {
                    if (e.key === "Enter" || e.key === " ") {
                      e.preventDefault();
                      onOpen();
                    }
                  }
                : undefined
            }
            role={onOpen ? "button" : undefined}
            tabIndex={onOpen ? 0 : undefined}
          >
            <div className="flex flex-wrap items-center gap-x-3 gap-y-1.5">
              <GstinCell
                gstin={gstin}
                truncate={false}
                className="font-mono text-[12px] text-gray-500"
              />
              <span className="text-[14px] font-semibold tracking-tight text-[var(--ink)]">
                {invoiceNumber}
              </span>
              <span className="text-[12px] text-gray-500">{invoiceDate}</span>
            </div>
            <div className="mt-2 flex flex-wrap items-center gap-2">
              <div className="rounded-full bg-[#F5F5F6] px-3 py-1">
                <span className="mr-1.5 text-[10px] font-medium uppercase tracking-wide text-gray-400">
                  {amountCaption}
                </span>
                <AmountDisplay amount={amount} />
              </div>
              {impact}
              {status}
              {meta}
            </div>
          </div>

          {trailing ? (
            <div className="flex w-full shrink-0 flex-wrap items-center gap-2 sm:ml-auto sm:w-auto sm:justify-end">
              {trailing}
            </div>
          ) : null}
        </div>

        {/* Decision block — structured for CAs */}
        <div className="grid gap-2 sm:grid-cols-3">
          <DecisionField label="What is wrong" value={what} />
          <DecisionField label="Why it happened" value={why} tone="muted" />
          <DecisionField label="What to do next" value={next} tone="action" />
        </div>

        {expandedContent ? (
          <div className="rounded-xl border border-[#F0F0F0] bg-[#FAFAFB] px-4 py-3">
            {expandedContent}
          </div>
        ) : null}
      </div>
    </article>
  );
}

export function DecisionInvoiceList({
  children,
  selectAll,
}: {
  children: ReactNode;
  selectAll?: ReactNode;
}) {
  return (
    <div className="space-y-3">
      {selectAll ? (
        <div className="flex items-center gap-3 rounded-[1rem] bg-white px-4 py-3 shadow-[var(--shadow-soft)] ring-1 ring-[#F0F0F0]">
          {selectAll}
        </div>
      ) : null}
      <div className="space-y-3">{children}</div>
    </div>
  );
}
