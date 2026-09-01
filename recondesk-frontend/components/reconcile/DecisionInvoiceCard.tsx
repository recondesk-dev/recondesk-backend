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
    <div className="min-w-0 rounded-[8px] border border-[#F1F5F9] bg-[#F8FAFC] px-3.5 py-2.5">
      <p className="text-[10px] font-semibold uppercase tracking-[0.4px] text-[#94A3B8]">
        {label}
      </p>
      <p className={`mt-1 text-[12px] leading-relaxed ${toneClass}`}>{text}</p>
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
      className={`rounded-[10px] bg-white border transition-shadow ${
        selected
          ? "border-[#2563EB] ring-1 ring-[#2563EB]/20 shadow-sm"
          : "border-[#E2E8F0] shadow-sm hover:shadow-md"
      }`}
    >
      <div className="flex flex-col gap-3.5 p-4 sm:p-4.5">
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
              <span className="text-[13px] font-semibold tracking-tight text-[#0F172A]">
                {invoiceNumber}
              </span>
              <span className="text-[12px] text-[#64748B]">{invoiceDate}</span>
            </div>
            <div className="mt-2 flex flex-wrap items-center gap-2">
              <div className="rounded-full bg-[#F1F5F9] px-2.5 py-0.5">
                <span className="mr-1 text-[10px] font-medium uppercase tracking-wide text-[#94A3B8]">
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
          <div className="rounded-[8px] border border-[#E2E8F0] bg-[#F8FAFC] px-4 py-3">
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
        <div className="flex items-center gap-3 rounded-[10px] border border-[#E2E8F0] bg-[#FAFAFA] px-4 py-2.5 shadow-sm">
          {selectAll}
        </div>
      ) : null}
      <div className="space-y-3">{children}</div>
    </div>
  );
}
