"use client";

import { Loader2 } from "lucide-react";
import { useCallback, useEffect, useMemo, useState } from "react";
import useSWR from "swr";

import { ReconcilePaginationFooter } from "@/components/reconcile/ReconcilePaginationFooter";
import {
  filterDropdownClass,
  filterRowClass,
  sectionContainerClass,
  SectionHeader,
  tableCellClass,
  tableClass,
  tableHeadCellClass,
  tableHeadClass,
  tableRowClass,
  tableWrapClass,
} from "@/components/reconcile/ResultsUi";
import {
  AUDIT_ACTION_OPTIONS,
  formatActivityDetails,
  formatActivityMessage,
  formatActivityTimestamp,
  formatAuditActionLabel,
  type AuditLogRow,
} from "@/lib/activityLog";
import { auditLogsApi, authApi, teamApi, type TeamMemberListItem } from "@/lib/api";

const PAGE_SIZE = 25;

function ActivityLogFilters({
  staffUserId,
  onStaffChange,
  staffOptions,
  action,
  onActionChange,
  fromDate,
  onFromDateChange,
  toDate,
  onToDateChange,
}: {
  staffUserId: string;
  onStaffChange: (v: string) => void;
  staffOptions: { id: string; label: string }[];
  action: string;
  onActionChange: (v: string) => void;
  fromDate: string;
  onFromDateChange: (v: string) => void;
  toDate: string;
  onToDateChange: (v: string) => void;
}) {
  return (
    <div className={`${filterRowClass} mb-4 flex-wrap items-end gap-3`}>
      <label className="flex flex-col gap-1">
        <span className="text-[11px] font-semibold uppercase tracking-widest text-gray-400">
          Staff
        </span>
        <select
          className={filterDropdownClass}
          value={staffUserId}
          onChange={(e) => onStaffChange(e.target.value)}
          aria-label="Filter by staff member"
        >
          <option value="">All staff</option>
          {staffOptions.map((o) => (
            <option key={o.id} value={o.id}>
              {o.label}
            </option>
          ))}
        </select>
      </label>
      <label className="flex flex-col gap-1">
        <span className="text-[11px] font-semibold uppercase tracking-widest text-gray-400">
          Action
        </span>
        <select
          className={filterDropdownClass}
          value={action}
          onChange={(e) => onActionChange(e.target.value)}
          aria-label="Filter by action type"
        >
          <option value="">All actions</option>
          {AUDIT_ACTION_OPTIONS.map((o) => (
            <option key={o.value} value={o.value}>
              {o.label}
            </option>
          ))}
        </select>
      </label>
      <label className="flex flex-col gap-1">
        <span className="text-[11px] font-semibold uppercase tracking-widest text-gray-400">
          From
        </span>
        <input
          type="date"
          className={filterDropdownClass}
          value={fromDate}
          onChange={(e) => onFromDateChange(e.target.value)}
          aria-label="From date"
        />
      </label>
      <label className="flex flex-col gap-1">
        <span className="text-[11px] font-semibold uppercase tracking-widest text-gray-400">
          To
        </span>
        <input
          type="date"
          className={filterDropdownClass}
          value={toDate}
          onChange={(e) => onToDateChange(e.target.value)}
          aria-label="To date"
        />
      </label>
    </div>
  );
}

function ActivityLogTable({
  rows,
  emptyMessage,
}: {
  rows: AuditLogRow[];
  emptyMessage: string;
}) {
  if (rows.length === 0) {
    return (
      <p className="py-8 text-center text-[13px] text-gray-500">{emptyMessage}</p>
    );
  }

  return (
    <div className={tableWrapClass}>
      <table className={tableClass}>
        <thead className={tableHeadClass}>
          <tr>
            <th className={tableHeadCellClass}>Timestamp</th>
            <th className={tableHeadCellClass}>Staff Name</th>
            <th className={tableHeadCellClass}>Action</th>
            <th className={tableHeadCellClass}>Client / Entity</th>
            <th className={tableHeadCellClass}>Details</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((row) => (
            <tr key={row.id} className={tableRowClass}>
              <td className={`${tableCellClass} text-[13px] text-gray-600 whitespace-nowrap`}>
                {formatActivityTimestamp(row.created_at)}
              </td>
              <td className={tableCellClass}>
                {row.user_name?.trim() || "—"}
              </td>
              <td className={tableCellClass}>
                {formatAuditActionLabel(row.action)}
              </td>
              <td className={tableCellClass}>
                {row.entity_label?.trim() || "—"}
              </td>
              <td className={`${tableCellClass} max-w-md text-[13px] text-gray-600`}>
                <span className="block text-[var(--text-primary)]">
                  {formatActivityMessage(row)}
                </span>
                <span className="mt-0.5 block text-gray-500">
                  {formatActivityDetails(row)}
                </span>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

export function ActivityLogPanel({ authToken }: { authToken: string }) {
  const [staffUserId, setStaffUserId] = useState("");
  const [actionFilter, setActionFilter] = useState("");
  const [fromDate, setFromDate] = useState("");
  const [toDate, setToDate] = useState("");
  const [page, setPage] = useState(1);

  const teamKey = authToken ? (["activity-log-team", authToken] as const) : null;
  const meKey = authToken ? (["activity-log-me", authToken] as const) : null;
  const { data: teamMembers } = useSWR(
    teamKey,
    ([, t]) => teamApi.list(t),
    { revalidateOnFocus: false }
  );
  const { data: me } = useSWR(
    meKey,
    ([, t]) => authApi.me(t),
    { revalidateOnFocus: false }
  );

  const staffOptions = useMemo(() => {
    const opts: { id: string; label: string }[] = [];
    const seen = new Set<string>();
    if (me?.id) {
      seen.add(me.id);
      opts.push({
        id: me.id,
        label: me.full_name?.trim() || me.email?.trim() || "Admin",
      });
    }
    const list = (teamMembers ?? []) as TeamMemberListItem[];
    for (const m of list) {
      const id = m.member_user_id?.trim();
      if (!id || seen.has(id)) continue;
      seen.add(id);
      opts.push({
        id,
        label: m.full_name?.trim() || m.email?.trim() || id.slice(0, 8),
      });
    }
    return opts.sort((a, b) => a.label.localeCompare(b.label));
  }, [me, teamMembers]);

  const queryParams = useMemo(() => {
    const offset = (page - 1) * PAGE_SIZE;
    const params: Parameters<typeof auditLogsApi.list>[1] = {
      limit: PAGE_SIZE,
      offset,
    };
    if (staffUserId) params.user_id = staffUserId;
    if (actionFilter) params.action = actionFilter;
    if (fromDate) params.from_date = `${fromDate}T00:00:00Z`;
    if (toDate) params.to_date = `${toDate}T23:59:59Z`;
    return params;
  }, [actionFilter, fromDate, page, staffUserId, toDate]);

  const swrKey = authToken
    ? (["audit-logs", authToken, queryParams] as const)
    : null;

  const { data, error, isLoading, mutate } = useSWR(
    swrKey,
    ([, token, params]) => auditLogsApi.list(token, params),
    { revalidateOnFocus: false, keepPreviousData: true }
  );

  const total = data?.total ?? 0;
  const totalPages = Math.max(1, Math.ceil(total / PAGE_SIZE));

  useEffect(() => {
    setPage(1);
  }, [staffUserId, actionFilter, fromDate, toDate]);

  useEffect(() => {
    if (page > totalPages) setPage(totalPages);
  }, [page, totalPages]);

  const handlePageSizeChange = useCallback((_size: number) => {
    setPage(1);
  }, []);

  return (
    <div className={sectionContainerClass}>
      <SectionHeader title="Activity Log" dotColor="#7C3AED" />
      <p className="mb-4 text-sm text-[var(--text-secondary)]">
        Track every action taken by admin and staff in your workspace.
      </p>
      <ActivityLogFilters
        staffUserId={staffUserId}
        onStaffChange={setStaffUserId}
        staffOptions={staffOptions}
        action={actionFilter}
        onActionChange={setActionFilter}
        fromDate={fromDate}
        onFromDateChange={setFromDate}
        toDate={toDate}
        onToDateChange={setToDate}
      />
      {error && (
        <div className="mb-4 rounded-lg border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-800">
          Failed to load activity log.{" "}
          <button
            type="button"
            className="font-medium underline"
            onClick={() => void mutate()}
          >
            Retry
          </button>
        </div>
      )}
      {isLoading && !data && !error ? (
        <p className="flex items-center gap-2 text-sm text-gray-400">
          <Loader2 className="h-4 w-4 animate-spin" aria-hidden />
          Loading activity…
        </p>
      ) : (
        <>
          <ActivityLogTable
            rows={data?.data ?? []}
            emptyMessage="No activity recorded for the selected filters."
          />
          <ReconcilePaginationFooter
            page={page}
            totalPages={totalPages}
            total={total}
            limit={PAGE_SIZE}
            onPrev={() => setPage((p) => Math.max(1, p - 1))}
            onNext={() => setPage((p) => Math.min(totalPages, p + 1))}
            disabled={isLoading}
            pageSize={PAGE_SIZE}
            pageSizeOptions={[25]}
            onPageSizeChange={handlePageSizeChange}
          />
        </>
      )}
    </div>
  );
}
