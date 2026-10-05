"use client";

import type { ReactNode } from "react";
import { ArrowRight, Search, ListChecks } from "lucide-react";
import styles from "./DecisionInvoiceCard.module.css";
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
      ? "font-semibold text-[var(--ink)]"
      : tone === "muted"
        ? "text-gray-500"
        : "text-gray-700";

  return (
    <div className={redesigned ? `${styles.field} ${tone === "action" ? styles.next : ""}` : "min-w-0 rounded-[8px] border border-[#F1F5F9] bg-[#F8FAFC] px-4 py-3"}>
      {redesigned && <span className={styles.step} aria-hidden="true">{tone === "action" ? <ArrowRight size={16} /> : tone === "muted" ? <Search size={16} /> : <ListChecks size={16} />}</span>}
      <p className={redesigned ? "text-xs font-semibold text-[#64748B]" : "text-[11px] font-bold uppercase tracking-[0.5px] text-[#64748B]"}>
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
      className={`${redesigned ? styles.invoice : ""} rounded-[10px] bg-white border transition-shadow ${
        selected
          ? "border-[#2563EB] ring-1 ring-[#2563EB]/20 shadow-sm"
          : "border-[#E2E8F0] shadow-sm hover:shadow-md"
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
        <div className={redesigned ? styles.decision : "grid gap-2 sm:grid-cols-3"}>
          <DecisionField redesigned={redesigned} label={t("whatIsWrong")} value={localizedWhat} />
          <DecisionField redesigned={redesigned} label={t("whyItHappened")} value={localizedWhy} tone="muted" />
          <DecisionField redesigned={redesigned} label={t("whatToDoNext")} value={localizedNext} tone="action" />
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
