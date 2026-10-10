"use client";

import { useMemo, useState } from "react";
import {
  Building2,
  ChevronDown,
  ChevronUp,
  FileCheck2,
  FileText,
  HelpCircle,
  Layers,
  Sparkles,
} from "lucide-react";

import {
  SectionHeader,
  sectionContainerClass,
} from "@/components/reconcile/ResultsUi";
import { formatINR } from "@/lib/format";
import type { Gstr1PortalMirror, Gstr1PortalTableTile } from "@/lib/api";

type CategoryFilter = "all" | "taxable" | "notes" | "other";

export function Gstr1PortalMirrorView({
  mirror,
  filingPeriod,
}: {
  mirror?: Gstr1PortalMirror | null;
  filingPeriod?: string | null;
}) {
  const [selectedCategory, setSelectedCategory] = useState<CategoryFilter>("all");
  const [expandedTable, setExpandedTable] = useState<string | null>(null);

  const tables = useMemo(() => {
    if (!mirror?.tables) return [];
    return Object.values(mirror.tables);
  }, [mirror]);

  const filteredTables = useMemo(() => {
    if (selectedCategory === "all") return tables;
    return tables.filter((t) => t.category === selectedCategory);
  }, [tables, selectedCategory]);

  if (!mirror || !tables.length) {
    return null;
  }

  const { totals } = mirror;

  const toggleExpand = (code: string) => {
    setExpandedTable((prev) => (prev === code ? null : code));
  };

  return (
    <section
      className={sectionContainerClass}
      aria-label="GST Portal Mirror View"
    >
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <div className="flex items-center gap-2">
            <SectionHeader
              title="GST Portal Mirror View (Form GSTR-1)"
              dotColor="#2563EB"
            />
            <span className="inline-flex items-center gap-1 rounded-full bg-blue-50 px-2.5 py-0.5 text-[11px] font-semibold text-blue-700 ring-1 ring-blue-200/60">
              <Sparkles className="h-3 w-3" />
              Portal Replica
            </span>
          </div>
          <p className="mt-1 text-[13px] text-gray-500">
            Statutory tile dashboard formatted exactly as reported on{" "}
            <code className="text-[12px] font-semibold text-gray-700">
              gst.gov.in
            </code>
            . Cross-verify table-wise invoice counts, taxable values, and tax heads before filing.
          </p>
        </div>

        {filingPeriod ? (
          <div className="rounded-full bg-[#F5F5F6] px-3.5 py-1 text-[12px] font-medium text-gray-600">
            Period: <span className="font-semibold text-gray-900">{filingPeriod}</span>
          </div>
        ) : null}
      </div>

      {/* Top Outward Liability Summary Bar */}
      <div className="mt-5 overflow-hidden rounded-2xl bg-[#0F172A] p-5 text-white shadow-sm ring-1 ring-black/5">
        <div className="flex flex-wrap items-center justify-between gap-2 border-b border-white/10 pb-3">
          <div className="flex items-center gap-2">
            <Building2 className="h-4 w-4 text-blue-400" />
            <span className="text-[12px] font-medium uppercase tracking-wider text-gray-300">
              Total Outward Supplies Liability
            </span>
          </div>
          <div className="flex items-center gap-2 text-[12px] text-gray-400">
            <span>
              {totals.total_invoices > 0
                ? `${totals.total_invoices} Invoices`
                : `${totals.total_records} Records`}
            </span>
            <span>·</span>
            <span>Ready for GSTN Upload</span>
          </div>
        </div>

        <div className="mt-4 grid grid-cols-2 gap-4 sm:grid-cols-3 lg:grid-cols-6">
          <div>
            <div className="text-[11px] uppercase tracking-wider text-gray-400">
              Taxable Value
            </div>
            <div className="mt-1 text-lg font-bold tabular-nums text-white">
              {formatINR(totals.total_taxable_value)}
            </div>
          </div>

          <div>
            <div className="text-[11px] uppercase tracking-wider text-gray-400">
              IGST (Integrated)
            </div>
            <div className="mt-1 text-lg font-bold tabular-nums text-blue-300">
              {formatINR(totals.total_igst)}
            </div>
          </div>

          <div>
            <div className="text-[11px] uppercase tracking-wider text-gray-400">
              CGST (Central)
            </div>
            <div className="mt-1 text-lg font-bold tabular-nums text-emerald-300">
              {formatINR(totals.total_cgst)}
            </div>
          </div>

          <div>
            <div className="text-[11px] uppercase tracking-wider text-gray-400">
              SGST (State)
            </div>
            <div className="mt-1 text-lg font-bold tabular-nums text-emerald-300">
              {formatINR(totals.total_sgst)}
            </div>
          </div>

          <div>
            <div className="text-[11px] uppercase tracking-wider text-gray-400">
              Cess
            </div>
            <div className="mt-1 text-lg font-bold tabular-nums text-purple-300">
              {formatINR(totals.total_cess)}
            </div>
          </div>

          <div className="rounded-xl bg-white/10 p-2.5">
            <div className="text-[11px] font-semibold uppercase tracking-wider text-amber-300">
              Total Tax Liability
            </div>
            <div className="mt-0.5 text-xl font-extrabold tabular-nums text-white">
              {formatINR(totals.total_tax)}
            </div>
          </div>
        </div>
      </div>

      {/* Filter Tabs */}
      <div className="mt-5 flex flex-wrap items-center gap-2 border-b border-gray-100 pb-3">
        <button
          type="button"
          onClick={() => setSelectedCategory("all")}
          className={`rounded-full px-3.5 py-1.5 text-[12px] font-semibold transition ${
            selectedCategory === "all"
              ? "bg-[#0F172A] text-white shadow-sm"
              : "bg-[#F5F5F6] text-gray-600 hover:bg-gray-200/60"
          }`}
        >
          All Tables ({tables.length})
        </button>
        <button
          type="button"
          onClick={() => setSelectedCategory("taxable")}
          className={`rounded-full px-3.5 py-1.5 text-[12px] font-semibold transition ${
            selectedCategory === "taxable"
              ? "bg-[#0F172A] text-white shadow-sm"
              : "bg-[#F5F5F6] text-gray-600 hover:bg-gray-200/60"
          }`}
        >
          Taxable Supplies (4, 5, 6A, 7)
        </button>
        <button
          type="button"
          onClick={() => setSelectedCategory("notes")}
          className={`rounded-full px-3.5 py-1.5 text-[12px] font-semibold transition ${
            selectedCategory === "notes"
              ? "bg-[#0F172A] text-white shadow-sm"
              : "bg-[#F5F5F6] text-gray-600 hover:bg-gray-200/60"
          }`}
        >
          Credit / Debit Notes (9B)
        </button>
        <button
          type="button"
          onClick={() => setSelectedCategory("other")}
          className={`rounded-full px-3.5 py-1.5 text-[12px] font-semibold transition ${
            selectedCategory === "other"
              ? "bg-[#0F172A] text-white shadow-sm"
              : "bg-[#F5F5F6] text-gray-600 hover:bg-gray-200/60"
          }`}
        >
          Other Tables (8, 12, 13)
        </button>
      </div>

      {/* Grid of GST Portal Tiles */}
      <div className="mt-4 grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
        {filteredTables.map((tile) => (
          <PortalTileCard
            key={tile.code}
            tile={tile}
            isExpanded={expandedTable === tile.code}
            onToggleExpand={() => toggleExpand(tile.code)}
          />
        ))}
      </div>
    </section>
  );
}

function PortalTileCard({
  tile,
  isExpanded,
  onToggleExpand,
}: {
  tile: Gstr1PortalTableTile;
  isExpanded: boolean;
  onToggleExpand: () => void;
}) {
  const isPopulated = tile.count > 0 || (tile.taxable_value > 0);

  return (
    <div
      className={`relative flex flex-col justify-between rounded-2xl border transition-all ${
        isPopulated
          ? "border-gray-200/90 bg-white shadow-sm hover:border-gray-300"
          : "border-dashed border-gray-200 bg-[#FAFAFB] opacity-75"
      }`}
    >
      <div className="p-4">
        {/* Card Header */}
        <div className="flex items-start justify-between gap-2">
          <div>
            <div className="flex items-center gap-1.5">
              <span className="rounded-md bg-gray-100 px-2 py-0.5 text-[11px] font-bold text-gray-800">
                Table {tile.table_id}
              </span>
              {isPopulated ? (
                <span className="inline-flex items-center gap-1 text-[11px] font-semibold text-emerald-600">
                  <span className="h-1.5 w-1.5 rounded-full bg-emerald-500" />
                  Populated
                </span>
              ) : (
                <span className="text-[11px] text-gray-400">Nil / Empty</span>
              )}
            </div>
            <h4 className="mt-1.5 text-[14px] font-bold tracking-tight text-[var(--ink)]">
              {tile.title}
            </h4>
          </div>

          <div className="text-right">
            <span className="text-xs font-semibold tabular-nums text-gray-900">
              {tile.count.toLocaleString("en-IN")}
            </span>
            <span className="block text-[11px] text-gray-500">
              {tile.count_label}
            </span>
            {tile.secondary_count != null && tile.secondary_count > 0 ? (
              <span className="block text-[10px] text-gray-400">
                {tile.secondary_count} {tile.secondary_count_label}
              </span>
            ) : null}
          </div>
        </div>

        {/* Primary Metrics */}
        <div className="mt-4 grid grid-cols-2 gap-3 rounded-xl bg-[#F8F9FA] p-3">
          <div>
            <span className="text-[11px] font-medium text-gray-500">
              Taxable Value
            </span>
            <p className="text-[13px] font-bold tabular-nums text-gray-900">
              {formatINR(tile.taxable_value)}
            </p>
          </div>

          <div>
            <span className="text-[11px] font-medium text-gray-500">
              Total Tax
            </span>
            <p className="text-[13px] font-bold tabular-nums text-blue-700">
              {formatINR(tile.total_tax)}
            </p>
          </div>
        </div>

        {/* Documents Issued specific info */}
        {tile.code === "doc_issue" && isPopulated ? (
          <div className="mt-2.5 flex items-center justify-between text-[11px] text-gray-500">
            <span>Net Issued: {tile.net_issued_count}</span>
            <span>Cancelled: {tile.cancelled_count}</span>
          </div>
        ) : null}

        {/* Nil / Exempt specific info */}
        {tile.code === "nil" && isPopulated ? (
          <div className="mt-2.5 space-y-1 text-[11px] text-gray-500">
            <div className="flex justify-between">
              <span>Nil Rated:</span>
              <span className="font-medium text-gray-700">
                {formatINR(tile.nil_amount || 0)}
              </span>
            </div>
            <div className="flex justify-between">
              <span>Exempted:</span>
              <span className="font-medium text-gray-700">
                {formatINR(tile.exempt_amount || 0)}
              </span>
            </div>
          </div>
        ) : null}

        {/* Expandable Tax Head Breakdown */}
        {isExpanded && isPopulated && tile.total_tax > 0 ? (
          <div className="mt-3 space-y-1.5 rounded-xl border border-blue-100 bg-blue-50/50 p-2.5 text-[12px]">
            <div className="flex justify-between">
              <span className="text-gray-600">IGST:</span>
              <span className="font-semibold tabular-nums text-blue-900">
                {formatINR(tile.igst)}
              </span>
            </div>
            <div className="flex justify-between">
              <span className="text-gray-600">CGST:</span>
              <span className="font-semibold tabular-nums text-emerald-900">
                {formatINR(tile.cgst)}
              </span>
            </div>
            <div className="flex justify-between">
              <span className="text-gray-600">SGST:</span>
              <span className="font-semibold tabular-nums text-emerald-900">
                {formatINR(tile.sgst)}
              </span>
            </div>
            {tile.cess > 0 ? (
              <div className="flex justify-between">
                <span className="text-gray-600">Cess:</span>
                <span className="font-semibold tabular-nums text-purple-900">
                  {formatINR(tile.cess)}
                </span>
              </div>
            ) : null}
          </div>
        ) : null}
      </div>

      {/* Card Footer toggle */}
      {isPopulated && tile.total_tax > 0 ? (
        <button
          type="button"
          onClick={onToggleExpand}
          className="flex w-full items-center justify-between border-t border-gray-100 bg-gray-50/60 px-4 py-2 text-[11px] font-semibold text-gray-600 transition hover:bg-gray-100/80"
        >
          <span>{isExpanded ? "Hide Tax Split" : "View Tax Split"}</span>
          {isExpanded ? (
            <ChevronUp className="h-3.5 w-3.5 text-gray-400" />
          ) : (
            <ChevronDown className="h-3.5 w-3.5 text-gray-400" />
          )}
        </button>
      ) : (
        <div className="border-t border-gray-100 px-4 py-2 text-[11px] text-gray-400">
          {isPopulated ? "No Tax Breakdown" : "No records for period"}
        </div>
      )}
    </div>
  );
}
