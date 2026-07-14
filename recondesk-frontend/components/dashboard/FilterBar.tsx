"use client";

import type { PortfolioFilters, PortfolioStatusFilter } from "@/lib/types";
import type { Staff } from "@/lib/types";

const STATUS_OPTIONS: { value: PortfolioStatusFilter; label: string }[] = [
  { value: "ALL", label: "All statuses" },
  { value: "PENDING", label: "Pending" },
  { value: "IN_PROGRESS", label: "In Progress" },
  { value: "COMPLETE", label: "Ready for Review" },
  { value: "FINALIZED", label: "Complete" },
  { value: "FAILED", label: "Failed" },
];

const selectClass =
  "min-w-[132px] appearance-none rounded-full border-0 bg-[#F5F5F6] px-4 py-2.5 text-sm font-medium text-gray-700 outline-none transition-shadow focus:ring-2 focus:ring-black/10";

export function FilterBar({
  filters,
  onChange,
  staff,
  periods,
  searchInput,
  onSearchInputChange,
  showReset,
  onReset,
}: {
  filters: PortfolioFilters;
  onChange: (next: PortfolioFilters) => void;
  staff: Staff[];
  periods: string[];
  searchInput: string;
  onSearchInputChange: (v: string) => void;
  showReset: boolean;
  onReset: () => void;
}) {
  return (
    <div className="flex flex-wrap items-center gap-2.5">
      <div className="relative min-w-[200px] flex-1">
        <svg
          className="pointer-events-none absolute left-3.5 top-1/2 h-4 w-4 -translate-y-1/2 text-gray-400"
          viewBox="0 0 24 24"
          fill="none"
          aria-hidden
        >
          <circle cx="11" cy="11" r="7" stroke="currentColor" strokeWidth="1.5" />
          <path d="M20 20l-3-3" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" />
        </svg>
        <input
          type="search"
          value={searchInput}
          onChange={(e) => onSearchInputChange(e.target.value)}
          placeholder="Search name or GSTIN"
          className="w-full rounded-full border-0 bg-[#F5F5F6] py-2.5 pl-10 pr-4 text-sm font-medium text-gray-700 outline-none transition-shadow placeholder:text-gray-400 focus:ring-2 focus:ring-black/10"
        />
      </div>
      <select
        value={filters.status}
        onChange={(e) =>
          onChange({ ...filters, status: e.target.value as PortfolioStatusFilter })
        }
        className={selectClass}
        aria-label="Status"
      >
        {STATUS_OPTIONS.map((o) => (
          <option key={o.value} value={o.value}>
            {o.label}
          </option>
        ))}
      </select>
      <select
        value={filters.assignedStaffId}
        onChange={(e) =>
          onChange({
            ...filters,
            assignedStaffId: e.target.value as PortfolioFilters["assignedStaffId"],
          })
        }
        className={selectClass}
        aria-label="Assigned to"
      >
        <option value="ALL">All staff</option>
        {staff.map((s) => (
          <option key={s.id} value={s.id}>
            {s.name}
          </option>
        ))}
      </select>
      <select
        value={filters.period}
        onChange={(e) => onChange({ ...filters, period: e.target.value })}
        className={selectClass}
        aria-label="Period"
      >
        <option value="ALL">All periods</option>
        {periods.map((p) => (
          <option key={p} value={p}>
            {p}
          </option>
        ))}
      </select>
      {showReset && (
        <button
          type="button"
          onClick={onReset}
          className="rounded-full px-3 py-2 text-sm font-medium text-gray-500 transition-colors hover:bg-gray-100 hover:text-gray-900"
        >
          Reset
        </button>
      )}
    </div>
  );
}
