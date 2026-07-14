"use client";

import Link from "next/link";
import { memo, useCallback, useMemo, useRef, useState } from "react";
import { Pie, PieChart, ResponsiveContainer, Cell } from "recharts";
import { useRouter } from "next/navigation";
import type { ClientPortfolioRow, PortfolioSortKey, SortDirection } from "@/lib/types";
import type { ComplianceRisk, ReconciliationStatus } from "@/lib/types";
import { formatInrFull } from "@/lib/format";
import { formatInrCompact } from "@/lib/format";
import { truncateGstin } from "@/lib/format";
import { StatusBadge } from "./StatusBadge";
import { Avatar } from "@/components/ui/Avatar";
import { Modal } from "@/components/ui/Modal";

function SortArrow({ active, dir }: { active: boolean; dir: SortDirection }) {
  if (!active) return <span className="ml-1 text-gray-300">↕</span>;
  return <span className="ml-1 text-[var(--ink)]">{dir === "asc" ? "↑" : "↓"}</span>;
}

function MatchRateBar({ rate }: { rate: number | null }) {
  if (rate == null) {
    return <span className="text-sm text-[var(--text-secondary)]">—</span>;
  }
  const color =
    rate < 70 ? "bg-[var(--danger)]" : rate < 90 ? "bg-[var(--warning)]" : "bg-[var(--success)]";
  return (
    <div className="flex items-center gap-2">
      <div className="h-2 w-full max-w-[100px] overflow-hidden rounded-full bg-gray-100">
        <div className={`h-full ${color}`} style={{ width: `${Math.min(100, rate)}%` }} />
      </div>
      <span className="font-mono text-xs text-[var(--text-primary)]">{rate}%</span>
    </div>
  );
}

function formatMissedSnippet(n: number): string {
  if (n >= 100000) return `${formatInrCompact(n)} missed`;
  return `${formatInrFull(n)} missed`;
}


function complianceRiskWords(r: ComplianceRisk | null | undefined): string {
  const level = r ?? "LOW";
  const map: Record<ComplianceRisk, string> = {
    LOW: "Low risk",
    MEDIUM: "Medium risk",
    HIGH: "High risk",
    CRITICAL: "Critical risk",
  };
  return map[level];
}

/** Display labels only — COMPLETE means processed (ready for review), not signed-off. */
function statusWord(status: ReconciliationStatus): string {
  const map: Record<ReconciliationStatus, string> = {
    PENDING: "Pending",
    IMPORTING: "Importing",
    MATCHING: "Matching",
    COMPLETE: "Ready for Review",
    FINALIZED: "Complete",
    FAILED: "Failed",
  };
  return map[status];
}

function WhyItMattersCell({ row }: { row: ClientPortfolioRow }) {
  const latest = row.latestRun;
  if (!latest) {
    return <span className="text-xs text-[var(--text-secondary)]">No runs yet</span>;
  }
  if (latest.status === "FINALIZED") {
    return <span className="text-xs text-[var(--text-secondary)]">Complete</span>;
  }
  if (latest.status === "FAILED") {
    return <span className="text-xs text-[var(--text-secondary)]">Failed — needs retry</span>;
  }

  const pipeline = latest.status === "PENDING" || latest.status === "IMPORTING" || latest.status === "MATCHING";
  if (pipeline && latest.missedItc == null && latest.complianceRisk == null) {
    if (latest.status === "PENDING") {
      return <span className="text-xs text-[var(--text-secondary)]">Pending</span>;
    }
    return (
      <span className="text-xs text-[var(--text-secondary)]">In progress — no data yet</span>
    );
  }

  const parts: string[] = [];
  if (latest.missedItc != null) {
    parts.push(formatMissedSnippet(latest.missedItc));
  }
  if (latest.complianceRisk != null) {
    parts.push(complianceRiskWords(latest.complianceRisk));
  }
  parts.push(statusWord(latest.status));

  return (
    <span className="text-xs leading-snug text-[var(--text-secondary)]">{parts.join(" • ")}</span>
  );
}

function riskParenClass(risk: ComplianceRisk | null | undefined): string {
  const level = risk ?? "LOW";
  if (level === "CRITICAL") return "text-[var(--danger)]";
  if (level === "HIGH") return "text-[var(--warning)]";
  if (level === "MEDIUM") return "text-[#F59E0B]";
  return "text-[var(--success)]";
}

function ItcAtRiskCell({ row }: { row: ClientPortfolioRow }) {
  const latest = row.latestRun;
  const v = latest?.missedItc;
  if (v == null) {
    return <span className="text-sm text-[var(--text-secondary)]">—</span>;
  }
  if (v === 0) {
    return (
      <span className="text-sm font-bold text-[var(--success)]">
        <span className="font-mono">₹0</span>
        <span className="font-normal"> (Low risk)</span>
      </span>
    );
  }
  const riskLabel = complianceRiskWords(latest?.complianceRisk).replace(" risk", "");
  return (
    <span className="text-sm">
      <span className="font-mono font-bold text-[var(--success)]">{formatInrFull(v)}</span>{" "}
      <span className={`font-medium ${riskParenClass(latest?.complianceRisk)}`}>
        ({riskLabel} risk)
      </span>
    </span>
  );
}

function TableLoadingRows() {
  const bar = (w: string) => (
    <div className={`h-4 animate-pulse rounded-lg bg-gray-100 ${w}`} />
  );
  return (
    <>
      {Array.from({ length: 5 }).map((_, i) => (
        <tr key={i} className="border-b border-gray-100">
          <td className="px-4 py-3.5">{bar("w-4")}</td>
          <td className="px-4 py-3.5">{bar("w-44")}</td>
          <td className="px-4 py-3.5">{bar("w-36")}</td>
          <td className="px-4 py-3.5">{bar("w-28")}</td>
          <td className="px-4 py-3.5">{bar("w-20")}</td>
          <td className="px-4 py-3.5">{bar("w-16")}</td>
          <td className="px-4 py-3.5">{bar("w-24")}</td>
          <td className="px-4 py-3.5">{bar("w-32")}</td>
          <td className="px-4 py-3.5">{bar("w-24")}</td>
          <td className="px-4 py-3.5">{bar("w-20")}</td>
        </tr>
      ))}
    </>
  );
}

function mockMismatchTop3(seed: string): { name: string; count: number }[] {
  let h = 0;
  for (let i = 0; i < seed.length; i++) h = (h + seed.charCodeAt(i) * (i + 1)) % 997;
  const base = [
    { name: "B2B invoice mismatch", count: 12 + (h % 8) },
    { name: "Credit / debit notes", count: 5 + (h % 5) },
    { name: "RCM / import services", count: 3 + (h % 4) },
  ];
  return base;
}

const PREVIEW_GREEN = "#10B981";
const PREVIEW_RED = "#EF4444";

const PortfolioRowInner = memo(function PortfolioRowInner({
  row,
  selected,
  onToggleSelect,
  onPreviewEnter,
  onPreviewLeave,
  onRetryClick,
}: {
  row: ClientPortfolioRow;
  selected: boolean;
  onToggleSelect: (id: string) => void;
  onPreviewEnter: (id: string, rect: DOMRect) => void;
  onPreviewLeave: () => void;
  onRetryClick: (row: ClientPortfolioRow) => void;
}) {
  const router = useRouter();
  const latest = row.latestRun;
  const status = latest?.status;

  const navigateDetail = () => router.push(`/clients/${row.client.id}`);
  const navigateToResults = () => {
    if (latest?.id) {
      router.push(`/reconcile/runs/${latest.id}/results`);
    }
  };

  const isFailed = status === "FAILED";
  const isFinalized = status === "FINALIZED";
  const rowBg = isFailed ? "bg-red-50/30" : "";
  const firstCellBorder = "";
  const rowOpacity = isFinalized ? "opacity-55" : "";
  const hoverClass = "hover:bg-[#F7F7F8]";

  return (
    <tr
      className={`cursor-pointer border-b border-[#F0F0F0] transition-colors last:border-b-0 ${rowBg} ${rowOpacity} ${hoverClass}`}
      onClick={navigateDetail}
      onMouseEnter={(e) => {
        if (latest?.status === "COMPLETE") {
          onPreviewEnter(row.client.id, e.currentTarget.getBoundingClientRect());
        }
      }}
      onMouseLeave={() => {
        if (latest?.status === "COMPLETE") onPreviewLeave();
      }}
    >
      <td
        className={`px-4 py-3.5 ${firstCellBorder}`}
        onClick={(e) => e.stopPropagation()}
      >
        <input
          type="checkbox"
          checked={selected}
          onChange={() => onToggleSelect(row.client.id)}
          className="h-4 w-4 rounded border-gray-200 accent-[var(--ink)]"
          aria-label={`Select ${row.client.tradeName}`}
        />
      </td>
      <td className="max-w-[220px] px-4 py-3.5">
        <WhyItMattersCell row={row} />
      </td>
      <td className="px-4 py-3.5">
        <Link
          href={`/clients/${row.client.id}`}
          className="font-medium text-[var(--ink)] hover:underline cursor-pointer"
        >
          {row.client.tradeName}
        </Link>
      </td>
      <td className="hidden px-4 py-3.5 font-mono text-[11px] text-gray-400 xl:table-cell">
        {row.client.gstin}
      </td>
      <td className="px-4 py-3.5 font-mono text-[11px] text-gray-400 xl:hidden">
        {truncateGstin(row.client.gstin)}
      </td>
      <td className="px-4 py-3.5">
        {!latest ? (
          <span className="text-sm text-gray-400">No reconciliations yet</span>
        ) : (
          <StatusBadge status={latest.status} />
        )}
      </td>
      <td className="px-4 py-3.5 text-xs text-gray-400">{latest?.period ?? "—"}</td>
      <td className="px-4 py-3.5">
        <MatchRateBar rate={latest?.matchRate ?? null} />
      </td>
      <td className="px-4 py-3.5">
        <ItcAtRiskCell row={row} />
      </td>
      <td className="px-4 py-3.5">
        <div className="flex items-center gap-2">
          <Avatar initials={row.assignedStaff.avatarInitials} size="sm" />
          <span className="text-sm text-[var(--text-primary)]">{row.assignedStaff.name}</span>
        </div>
      </td>
      <td className="px-4 py-3.5" onClick={(e) => e.stopPropagation()}>
        <div className="flex justify-end">
          {status === "FINALIZED" && (
            <span className="text-xs text-gray-400">Done</span>
          )}
          {status === "COMPLETE" && (
            <button
              type="button"
              className="rounded-full bg-[var(--ink)] px-4 py-1.5 text-xs font-semibold text-white transition-opacity hover:opacity-90 focus:outline-none focus:ring-2 focus:ring-black/20"
              onClick={() => navigateToResults()}
            >
              Review
            </button>
          )}
          {status === "FAILED" && (
            <button
              type="button"
              className="rounded-full border border-[var(--danger)] bg-transparent px-4 py-1.5 text-xs font-semibold text-[var(--danger)] hover:bg-red-50 transition-colors"
              onClick={() => onRetryClick(row)}
            >
              Retry
            </button>
          )}
          {status === "PENDING" && (
            <button
              type="button"
              className="rounded-full bg-[var(--ink)] px-4 py-1.5 text-xs font-semibold text-white hover:opacity-90 transition-opacity"
              onClick={() => navigateDetail()}
            >
              Start
            </button>
          )}
          {!latest && (
            <button
              type="button"
              className="rounded-full bg-[var(--ink)] px-4 py-1.5 text-xs font-semibold text-white hover:opacity-90 transition-opacity"
              onClick={() => navigateDetail()}
            >
              Start
            </button>
          )}
          {(status === "IMPORTING" || status === "MATCHING") && (
            <button
              type="button"
              disabled
              className="cursor-not-allowed rounded-full bg-[#F0F0F0] px-4 py-1.5 text-xs font-semibold text-gray-400"
            >
              In Progress
            </button>
          )}
        </div>
      </td>
    </tr>
  );
});

function PreviewPopover({
  anchor,
  row,
  categories,
  onMouseEnter,
  onMouseLeave,
}: {
  anchor: { top: number; left: number };
  row: ClientPortfolioRow;
  categories: { name: string; count: number }[];
  onMouseEnter: () => void;
  onMouseLeave: () => void;
}) {
  const latest = row.latestRun;
  if (!latest || latest.status !== "COMPLETE" || latest.matchRate == null) return null;

  const matchRate = latest.matchRate;
  const data = [
    { name: "matched", value: matchRate, fill: PREVIEW_GREEN },
    { name: "rest", value: Math.max(0, 100 - matchRate), fill: PREVIEW_RED },
  ];

  return (
    <div
      className="pointer-events-auto fixed z-[60] w-64 rounded-[1.5rem] bg-white p-5 shadow-[var(--shadow-lift)] ring-1 ring-black/[0.04]"
      style={{
        top: anchor.top,
        left: anchor.left + 8,
      }}
      onMouseEnter={onMouseEnter}
      onMouseLeave={onMouseLeave}
    >
      <p className="text-[11px] font-medium uppercase tracking-widest text-gray-400">Quick preview</p>
      <div className="mt-3 flex gap-3">
        <div className="h-20 w-20 shrink-0">
          <ResponsiveContainer width="100%" height="100%">
            <PieChart>
              <Pie
                data={data}
                dataKey="value"
                nameKey="name"
                innerRadius={22}
                outerRadius={36}
                startAngle={90}
                endAngle={-270}
                stroke="none"
              >
                {data.map((e, i) => (
                  <Cell key={i} fill={e.fill} />
                ))}
              </Pie>
            </PieChart>
          </ResponsiveContainer>
        </div>
        <div className="min-w-0 flex-1">
          <p className="font-mono text-lg font-semibold text-gray-900">{matchRate}%</p>
          <p className="text-xs text-gray-400">match rate</p>
        </div>
      </div>
      <ul className="mt-3 space-y-1.5 text-xs text-gray-700">
        {categories.map((c) => (
          <li key={c.name} className="flex justify-between gap-2">
            <span className="truncate">{c.name}</span>
            <span className="font-mono text-gray-400">{c.count}</span>
          </li>
        ))}
      </ul>
      <p className="mt-3 font-mono text-sm font-semibold text-[var(--success)]">
        {latest.missedItc != null
          ? `${formatInrFull(latest.missedItc)} missed ITC — ${latest.period}`
          : `— — ${latest.period}`}
      </p>
      <Link
        href={`/clients/${row.client.id}`}
        className="mt-3 inline-block text-xs font-semibold text-[var(--ink)] hover:underline"
      >
        Open Full Report →
      </Link>
    </div>
  );
}

export function ClientTable({
  rows,
  loading,
  page,
  pageSize,
  total,
  onPageChange,
  sort,
  onSortToggle,
  selectedIds,
  onToggleSelect,
  onToggleAllOnPage,
  onRetryConfirm,
  onFinalizeConfirm: _onFinalizeConfirm,
}: {
  rows: ClientPortfolioRow[];
  loading: boolean;
  page: number;
  pageSize: number;
  total: number;
  onPageChange: (p: number) => void;
  sort: { key: PortfolioSortKey; dir: SortDirection };
  onSortToggle: (key: PortfolioSortKey) => void;
  selectedIds: Set<string>;
  onToggleSelect: (id: string) => void;
  onToggleAllOnPage: (ids: string[], checked: boolean) => void;
  onRetryConfirm: (row: ClientPortfolioRow) => void;
  onFinalizeConfirm: (row: ClientPortfolioRow) => void;
}) {
  void _onFinalizeConfirm;
  const [previewId, setPreviewId] = useState<string | null>(null);
  const [previewAnchor, setPreviewAnchor] = useState<{ top: number; left: number } | null>(null);
  const previewLeaveTimer = useRef<ReturnType<typeof setTimeout> | null>(null);

  const clearPreviewTimer = () => {
    if (previewLeaveTimer.current) {
      clearTimeout(previewLeaveTimer.current);
      previewLeaveTimer.current = null;
    }
  };

  const onPreviewEnter = useCallback((id: string, rect: DOMRect) => {
    clearPreviewTimer();
    setPreviewId(id);
    setPreviewAnchor({ top: rect.top, left: rect.right });
  }, []);

  const onPreviewLeave = useCallback(() => {
    clearPreviewTimer();
    previewLeaveTimer.current = setTimeout(() => {
      setPreviewId(null);
      setPreviewAnchor(null);
    }, 200);
  }, []);

  const onPopoverEnter = useCallback(() => {
    clearPreviewTimer();
  }, []);

  const previewRow = useMemo(
    () => rows.find((r) => r.client.id === previewId) ?? null,
    [rows, previewId]
  );

  const pageIds = useMemo(() => rows.map((r) => r.client.id), [rows]);
  const allSelected = pageIds.length > 0 && pageIds.every((id) => selectedIds.has(id));

  const start = total === 0 ? 0 : (page - 1) * pageSize + 1;
  const end = Math.min(page * pageSize, total);
  const maxPage = Math.max(1, Math.ceil(total / pageSize));

  return (
    <div className="relative overflow-hidden bg-white">
      <div className="overflow-x-auto">
        <table className="min-w-[1100px] w-full border-collapse text-left">
          <thead>
            <tr className="border-b border-[#F0F0F0] text-[11px] font-medium uppercase tracking-widest text-gray-400">
              <th className="w-10 px-5 py-4">
                <input
                  type="checkbox"
                  checked={allSelected}
                  disabled={loading || rows.length === 0}
                  onChange={(e) => onToggleAllOnPage(pageIds, e.target.checked)}
                  className="h-4 w-4 rounded border-gray-200 accent-[var(--ink)]"
                  aria-label="Select all on page"
                />
              </th>
              <th className="px-4 py-4">
                <button
                  type="button"
                  className="inline-flex items-center font-medium"
                  onClick={() => onSortToggle("priority")}
                >
                  Why it matters
                  <SortArrow active={sort.key === "priority"} dir={sort.dir} />
                </button>
              </th>
              <th className="px-4 py-4">Client Name</th>
              <th className="px-4 py-4">GSTIN</th>
              <th className="px-4 py-4">Status</th>
              <th className="px-4 py-4">Period</th>
              <th className="px-4 py-4">
                <button
                  type="button"
                  className="inline-flex items-center font-medium"
                  onClick={() => onSortToggle("matchRate")}
                >
                  Match Rate
                  <SortArrow active={sort.key === "matchRate"} dir={sort.dir} />
                </button>
              </th>
              <th className="px-4 py-4">
                <button
                  type="button"
                  className="inline-flex items-center font-medium"
                  onClick={() => onSortToggle("missedItc")}
                >
                  ITC at Risk
                  <SortArrow active={sort.key === "missedItc"} dir={sort.dir} />
                </button>
              </th>
              <th className="px-4 py-4">Assigned To</th>
              <th className="min-w-[100px] px-5 py-4 text-right">Actions</th>
            </tr>
          </thead>
          <tbody>
            {loading && <TableLoadingRows />}
            {!loading &&
              rows.map((row) => (
                <PortfolioRowInner
                  key={row.client.id}
                  row={row}
                  selected={selectedIds.has(row.client.id)}
                  onToggleSelect={onToggleSelect}
                  onPreviewEnter={onPreviewEnter}
                  onPreviewLeave={onPreviewLeave}
                  onRetryClick={onRetryConfirm}
                />
              ))}
          </tbody>
        </table>
      </div>
      {previewRow && previewAnchor && (
        <PreviewPopover
          anchor={previewAnchor}
          row={previewRow}
          categories={mockMismatchTop3(previewRow.client.id)}
          onMouseEnter={onPopoverEnter}
          onMouseLeave={onPreviewLeave}
        />
      )}
      <div className="flex flex-wrap items-center justify-between gap-3 border-t border-[#F0F0F0] bg-white px-5 py-4 text-sm text-gray-400">
        <span>
          Showing {start}–{end} of {total} clients
        </span>
        <div className="flex gap-2">
          <button
            type="button"
            disabled={page <= 1 || loading}
            onClick={() => onPageChange(page - 1)}
            className="rounded-full bg-[#F5F5F6] px-4 py-1.5 text-sm font-medium text-gray-600 transition-colors hover:bg-gray-200/70 disabled:opacity-30"
          >
            Previous
          </button>
          <button
            type="button"
            disabled={page >= maxPage || loading}
            onClick={() => onPageChange(page + 1)}
            className="rounded-full bg-[var(--ink)] px-4 py-1.5 text-sm font-medium text-white transition-opacity hover:opacity-90 disabled:opacity-30"
          >
            Next
          </button>
        </div>
      </div>
    </div>
  );
}

export function RetryConfirmModal({
  open,
  row,
  onClose,
  onConfirm,
  loading,
}: {
  open: boolean;
  row: ClientPortfolioRow | null;
  onClose: () => void;
  onConfirm: () => void;
  loading?: boolean;
}) {
  return (
    <Modal
      open={open}
      onClose={onClose}
      title="Retry reconciliation"
      footer={
        <>
          <button
            type="button"
            onClick={onClose}
            className="rounded-full border border-gray-200 px-4 py-2 text-sm font-medium text-gray-600 hover:bg-gray-50 transition-colors"
          >
            Cancel
          </button>
          <button
            type="button"
            disabled={loading}
            onClick={onConfirm}
            className="rounded-full bg-[var(--ink)] px-4 py-2 text-sm font-semibold text-white disabled:opacity-50 hover:opacity-90 transition-opacity"
          >
            Retry
          </button>
        </>
      }
    >
      {row && row.latestRun && (
        <p className="text-sm text-[var(--text-primary)]">
          Retry reconciliation for <strong>{row.client.tradeName}</strong> —{" "}
          <span className="font-mono">{row.latestRun.period}</span>?
        </p>
      )}
    </Modal>
  );
}
