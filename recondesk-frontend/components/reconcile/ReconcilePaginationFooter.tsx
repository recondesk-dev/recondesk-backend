"use client";

import type { ReactNode } from "react";

import { filterDropdownClass } from "@/components/reconcile/ResultsUi";

export function ReconcilePaginationFooter({
  page,
  totalPages,
  total,
  limit,
  onPrev,
  onNext,
  disabled,
  summary,
  pageSizeOptions,
  pageSize,
  onPageSizeChange,
}: {
  page: number;
  totalPages: number;
  total: number;
  limit: number;
  onPrev: () => void;
  onNext: () => void;
  disabled?: boolean;
  summary?: ReactNode;
  pageSizeOptions?: readonly number[];
  pageSize?: number;
  onPageSizeChange?: (size: number) => void;
}) {
  const from = total === 0 ? 0 : (page - 1) * limit + 1;
  const to = Math.min(page * limit, total);
  const showPageSize =
    pageSizeOptions != null &&
    pageSizeOptions.length > 0 &&
    pageSize != null &&
    onPageSizeChange != null;

  return (
    <div className="mt-3 flex w-full flex-wrap items-center justify-between gap-2">
      <div className="flex min-w-0 flex-wrap items-center gap-3">
        {summary != null ? (
          <p className="min-w-0 truncate text-[13px]">{summary}</p>
        ) : (
          <p className="truncate text-sm text-gray-500">
            Showing {from}–{to} of {total.toLocaleString("en-IN")} records
          </p>
        )}
        {showPageSize ? (
          <label className="flex items-center gap-2 text-sm text-gray-500">
            <span className="whitespace-nowrap">Rows per page</span>
            <select
              value={pageSize}
              onChange={(e) => onPageSizeChange(Number(e.target.value))}
              className={`${filterDropdownClass} min-h-[36px] text-[13px]`}
              aria-label="Rows per page"
            >
              {pageSizeOptions.map((n) => (
                <option key={n} value={n}>
                  {n}
                </option>
              ))}
            </select>
          </label>
        ) : null}
      </div>
      <div className="flex shrink-0 gap-2">
        <button
          type="button"
          disabled={disabled || page <= 1}
          onClick={onPrev}
          className="min-h-[40px] rounded-full bg-[#F5F5F6] px-4 py-1.5 text-sm font-medium text-gray-700 transition-colors hover:bg-gray-200/70 disabled:opacity-40"
        >
          Previous
        </button>
        <button
          type="button"
          disabled={disabled || page >= totalPages}
          onClick={onNext}
          className="min-h-[40px] rounded-full bg-[var(--ink)] px-4 py-1.5 text-sm font-medium text-white transition-opacity hover:opacity-90 disabled:opacity-40"
        >
          Next
        </button>
      </div>
    </div>
  );
}
