"use client";

import type { ReactNode } from "react";
import { useLocale, useTranslations } from "next-intl";

import { AmountDisplay } from "@/components/reconcile/ResultsUi";
import { GstinCell } from "@/components/ui/GstinCell";
import { localizeDecisionText } from "@/lib/decision-translations";

function DecisionField({
  label,
  value,
  tone = "default",
  redesigned = false,
}: {
  label: string;
  value: string | null | undefined;
  tone?: "default" | "muted" | "action";
  redesigned?: boolean;
}) {
  const text = value?.trim() || "—";
  const toneClass =
    tone === "action"
      ? "font-semibold text-[#554260]"
      : tone === "muted"
        ? "text-[#594c66]"
        : "text-[#342b40]";

  const bgClass =
    tone === "action"
      ? "bg-[#f4f0fa] border-[#e8e0f1]"
      : "bg-[#faf9fc] border-[#eee8f4]";

  return (
    <div className={`min-w-0 rounded-[8px] border px-4 py-3 ${bgClass}`}>
      <p className="text-[11px] font-bold uppercase tracking-[0.5px] text-[#78608f]">
        {label}
      </p>
      <p className={`mt-1 text-[13px] leading-relaxed ${toneClass}`}>{text}</p>
    </div>
  );
}

export function DecisionInvoiceCard({
  index,
  gstin,
  invoiceNumber,
  invoiceDate,
  amount,
  amountCaption,
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
  redesigned = false,
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
  redesigned?: boolean;
}) {
  const selectable = typeof onSelectChange === "function";
  const t = useTranslations("decisionCard");
  const locale = useLocale();
  const resolvedAmountCaption = amountCaption ?? t("amount");

  const localizedWhat = localizeDecisionText(what, locale);
  const localizedWhy = localizeDecisionText(why, locale);
  const localizedNext = localizeDecisionText(next, locale);

  return (
    <article
      className={`rounded-[12px] bg-white border transition-shadow ${
        selected
          ? "border-[#78608f] ring-1 ring-[#78608f]/20 shadow-xs"
          : "border-[#e8e0f1] shadow-xs hover:shadow-sm"
      }`}
    >
      <div className="flex flex-col gap-3.5 p-5">
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
            <span className="w-6 text-[13px] font-semibold tabular-nums text-gray-400">#{index}</span>
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
            <div className="flex flex-wrap items-center gap-x-3.5 gap-y-1.5">
              <GstinCell
                gstin={gstin}
                truncate={false}
                className="font-mono text-xs sm:text-[13px] font-semibold text-gray-600"
              />
              <span className="text-sm sm:text-[15px] font-bold tracking-tight text-[#0F172A]">
                {invoiceNumber}
              </span>
              <span className="text-xs sm:text-[13px] text-[#64748B]">{invoiceDate}</span>
            </div>
            <div className="mt-2.5 flex flex-wrap items-center gap-2">
              <div className="rounded-full bg-[#F1F5F9] px-3 py-0.5">
                <span className="mr-1 text-[11px] font-bold uppercase tracking-wide text-[#94A3B8]">
                  {resolvedAmountCaption}
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
          <DecisionField label={t("whatIsWrong")} value={localizedWhat} />
          <DecisionField label={t("whyItHappened")} value={localizedWhy} tone="muted" />
          <DecisionField label={t("whatToDoNext")} value={localizedNext} tone="action" />
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
