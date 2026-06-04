"use client";

import type { PortfolioFilters, PortfolioStatusFilter } from "@/lib/types";
import type { Staff } from "@/lib/types";

const STATUS_OPTIONS: { value: PortfolioStatusFilter; label: string }[] = [
  { value: "ALL", label: "All" },
  { value: "PENDING", label: "Pending" },
  { value: "IN_PROGRESS", label: "In Progress" },
  { value: "COMPLETE", label: "Complete" },
  { value: "FINALIZED", label: "Finalized" },
  { value: "FAILED", label: "Failed" },
];

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
    <div className="flex flex-wrap items-end gap-4 rounded-2xl bg-white p-5 shadow-sm">
      <div>
        <label className="mb-1 block text-[11px] font-medium uppercase tracking-widest text-gray-400">Status</label>
        <select
          value={filters.status}
          onChange={(e) =>
            onChange({ ...filters, status: e.target.value as PortfolioStatusFilter })
          }
          className="min-w-[140px] rounded-xl border border-gray-200 bg-gray-50 px-3 py-2 text-sm text-gray-700 outline-none focus:ring-2 focus:ring-brand"
        >
          {STATUS_OPTIONS.map((o) => (
            <option key={o.value} value={o.value}>
              {o.label}
            </option>
          ))}
        </select>
      </div>
      <div>
        <label className="mb-1 block text-[11px] font-medium uppercase tracking-widest text-gray-400">
          Assigned To
        </label>
        <select
          value={filters.assignedStaffId}
          onChange={(e) =>
            onChange({ ...filters, assignedStaffId: e.target.value as PortfolioFilters["assignedStaffId"] })
          }
          className="min-w-[160px] rounded-xl border border-gray-200 bg-gray-50 px-3 py-2 text-sm text-gray-700 outline-none focus:ring-2 focus:ring-brand"
        >
          <option value="ALL">All</option>
          {staff.map((s) => (
            <option key={s.id} value={s.id}>
              {s.name}
            </option>
          ))}
        </select>
      </div>
      <div>
        <label className="mb-1 block text-[11px] font-medium uppercase tracking-widest text-gray-400">Period</label>
        <select
          value={filters.period}
          onChange={(e) => onChange({ ...filters, period: e.target.value })}
          className="min-w-[120px] rounded-xl border border-gray-200 bg-gray-50 px-3 py-2 text-sm text-gray-700 outline-none focus:ring-2 focus:ring-brand"
        >
          <option value="ALL">All</option>
          {periods.map((p) => (
            <option key={p} value={p}>
              {p}
            </option>
          ))}
        </select>
      </div>
      <div className="min-w-[200px] flex-1">
        <label className="mb-1 block text-[11px] font-medium uppercase tracking-widest text-gray-400">Search</label>
        <input
          type="search"
          value={searchInput}
          onChange={(e) => onSearchInputChange(e.target.value)}
          placeholder="Name or GSTIN"
          className="w-full rounded-xl border border-gray-200 bg-gray-50 px-3 py-2 text-sm text-gray-700 outline-none focus:ring-2 focus:ring-brand"
        />
      </div>
      {showReset && (
        <button
          type="button"
          onClick={onReset}
          className="text-sm font-medium text-brand hover:underline"
        >
          Reset Filters
        </button>
      )}
    </div>
  );
}
