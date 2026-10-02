"use client";

import type { PortfolioFilters, PortfolioStatusFilter } from "@/lib/types";
import type { Staff } from "@/lib/types";
import { formatPeriodLabel } from "@/lib/dashboard-portfolio";

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
  density = "comfortable",
  onDensityChange,
}: {
  filters: PortfolioFilters;
  onChange: (next: PortfolioFilters) => void;
  staff: Staff[];
  periods: string[];
  searchInput: string;
  onSearchInputChange: (v: string) => void;
  showReset: boolean;
  onReset: () => void;
  density?: "comfortable" | "compact";
  onDensityChange?: (d: "comfortable" | "compact") => void;
}) {
  const quickPeriods = periods.slice(0, 3);

  return (
    <div className="space-y-2.5">
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
            aria-label="Search clients by name or GSTIN"
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

        {onDensityChange && (
          <div className="flex items-center rounded-full bg-[#F5F5F6] p-1" title="Row density">
            <button
              type="button"
              onClick={() => onDensityChange("comfortable")}
              aria-label="Comfortable density"
              title="Comfortable view"
              className={`flex items-center gap-1 rounded-full px-2.5 py-1.5 text-xs font-medium transition-colors ${
                density === "comfortable"
                  ? "bg-white text-[var(--ink)] shadow-sm font-semibold"
                  : "text-gray-500 hover:text-gray-800"
              }`}
            >
              <svg width="13" height="13" viewBox="0 0 24 24" fill="none">
                <path d="M4 7h16M4 17h16" stroke="currentColor" strokeWidth="2" strokeLinecap="round" />
              </svg>
              Comfortable
            </button>
            <button
              type="button"
              onClick={() => onDensityChange("compact")}
              aria-label="Compact density"
              title="Compact view"
              className={`flex items-center gap-1 rounded-full px-2.5 py-1.5 text-xs font-medium transition-colors ${
                density === "compact"
                  ? "bg-white text-[var(--ink)] shadow-sm font-semibold"
                  : "text-gray-500 hover:text-gray-800"
              }`}
            >
              <svg width="13" height="13" viewBox="0 0 24 24" fill="none">
                <path d="M4 6h16M4 12h16M4 18h16" stroke="currentColor" strokeWidth="2" strokeLinecap="round" />
              </svg>
              Compact
            </button>
          </div>
        )}

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

      {quickPeriods.length > 0 && (
        <div className="flex flex-wrap items-center gap-1.5 text-xs">
          <span className="font-medium text-gray-400 mr-1">Quick Period:</span>
          <button
            type="button"
            onClick={() => onChange({ ...filters, period: "ALL" })}
            className={`rounded-full px-3 py-1 font-medium transition-colors ${
              filters.period === "ALL"
                ? "bg-[var(--ink)] text-white"
                : "bg-[#F5F5F6] text-gray-600 hover:text-gray-900"
            }`}
          >
            All Periods
          </button>
          {quickPeriods.map((p) => {
            const isSelected = filters.period === p;
            return (
              <button
                key={p}
                type="button"
                onClick={() => onChange({ ...filters, period: isSelected ? "ALL" : p })}
                className={`rounded-full px-3 py-1 font-medium transition-colors ${
                  isSelected
                    ? "bg-[var(--ink)] text-white"
                    : "bg-[#F5F5F6] text-gray-600 hover:text-gray-900"
                }`}
              >
                {formatPeriodLabel(p)}
              </button>
            );
          })}
        </div>
      )}
    </div>
  );
}
