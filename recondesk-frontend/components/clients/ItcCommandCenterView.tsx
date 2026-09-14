"use client";

import { useState } from "react";
import Link from "next/link";
import useSWR, { mutate as swrMutate } from "swr";
import { formatINR } from "@/lib/format";
import {
  clientsApi,
  ItcCommandCenterResponse,
  ItcWorkItem,
  Table4BlockingRecordItem,
} from "@/lib/api";
import { Table4DispositionModal } from "@/components/reconcile/Table4DispositionModal";
import { ItcWorkItemDetailDrawer } from "./ItcWorkItemDetailDrawer";

interface ItcCommandCenterViewProps {
  clientId: string;
  authToken: string;
}

export function ItcCommandCenterView({
  clientId,
  authToken,
}: ItcCommandCenterViewProps) {
  const [selectedPeriod, setSelectedPeriod] = useState<string | undefined>(undefined);
  const [activePriorityTab, setActivePriorityTab] = useState<string>("ALL");
  const [selectedExceptionType, setSelectedExceptionType] = useState<string>("");
  const [searchQuery, setSearchQuery] = useState<string>("");
  const [expandedItemId, setExpandedItemId] = useState<string | null>(null);
  const [selectedDetailItem, setSelectedDetailItem] = useState<ItcWorkItem | null>(null);

  // Disposition modal state
  const [isDispositionModalOpen, setIsDispositionModalOpen] = useState(false);
  const [targetDispositionRecord, setTargetDispositionRecord] = useState<Table4BlockingRecordItem | null>(null);
  const [actionSuccessMsg, setActionSuccessMsg] = useState<string | null>(null);

  const swrKey = authToken && clientId
    ? [
        "itc-command-center",
        clientId,
        selectedPeriod || "latest",
        activePriorityTab,
        selectedExceptionType,
        searchQuery,
      ]
    : null;

  const { data, error, isLoading, mutate } = useSWR<ItcCommandCenterResponse>(
    swrKey,
    () =>
      clientsApi.getCommandCenter(authToken, clientId, {
        period: selectedPeriod,
        priority: activePriorityTab === "ALL" ? undefined : activePriorityTab,
        exception_type: selectedExceptionType || undefined,
        search: searchQuery || undefined,
      }),
    { refreshInterval: 0 }
  );

  const handleOpenDisposition = (item: ItcWorkItem) => {
    const blockingItem: Table4BlockingRecordItem = {
      record_id: item.record_id,
      exception_type: item.exception_type,
      supplier_name: item.supplier_name,
      supplier_gstin: item.supplier_gstin,
      invoice_number: item.invoice_number,
      amount: item.itc_impact,
      reason: item.why || item.what,
    };
    setTargetDispositionRecord(blockingItem);
    setIsDispositionModalOpen(true);
  };

  if (isLoading && !data) {
    return (
      <div className="flex flex-col items-center justify-center py-24 gap-3">
        <svg className="h-8 w-8 animate-spin text-black" fill="none" viewBox="0 0 24 24">
          <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
          <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8v8z" />
        </svg>
        <p className="text-[13px] text-gray-500">Loading ITC Command Center…</p>
      </div>
    );
  }

  if (error || !data) {
    return (
      <div className="rounded-2xl border border-red-200 bg-red-50 p-6 text-center">
        <p className="text-[14px] font-semibold text-red-800">
          Failed to load ITC Command Center
        </p>
        <p className="mt-1 text-[12px] text-red-600">
          {error?.detail || error?.message || "Please refresh the page or select another client."}
        </p>
      </div>
    );
  }

  const { client, periods, kpis, summary_counts, work_items, run_id, run_status, is_locked, audit_hash } = data;

  const getPriorityBadgeClass = (priority: string) => {
    switch (priority) {
      case "CRITICAL":
        return "bg-rose-100 text-rose-800 border-rose-200";
      case "HIGH":
        return "bg-amber-100 text-amber-900 border-amber-200";
      case "MEDIUM":
        return "bg-blue-100 text-blue-800 border-blue-200";
      default:
        return "bg-gray-100 text-gray-700 border-gray-200";
    }
  };

  return (
    <div className="space-y-6">
      {/* Toast Notification */}
      {actionSuccessMsg && (
        <div className="rounded-xl border border-green-200 bg-green-50 px-4 py-3 text-[13px] font-medium text-green-800 flex items-center justify-between shadow-xs">
          <span>{actionSuccessMsg}</span>
          <button onClick={() => setActionSuccessMsg(null)} className="text-green-600 hover:text-green-900">
            ×
          </button>
        </div>
      )}

      {/* 1. Header Banner & Period Selector */}
      <div className="rounded-2xl border border-gray-200 bg-white p-6 shadow-xs">
        <div className="flex flex-wrap items-start justify-between gap-4">
          <div>
            <div className="flex items-center gap-2.5">
              <span className="rounded-md bg-black px-2.5 py-0.5 text-[11px] font-bold text-white uppercase tracking-wider">
                Command Center
              </span>
              <h1 className="text-[20px] font-bold text-gray-900">
                {client.trade_name || client.legal_name}
              </h1>
              <span className="font-mono text-[12px] font-semibold text-gray-500 bg-gray-100 px-2 py-0.5 rounded">
                {client.gstin}
              </span>
            </div>
            <p className="mt-1.5 text-[13px] text-gray-500">
              Executive ITC control, actionable exception work items, and statutory compliance status.
            </p>
          </div>

          <div className="flex flex-wrap items-center gap-3">
            {/* Period Dropdown */}
            {periods.length > 0 && (
              <div className="flex items-center gap-2 bg-gray-50 border border-gray-200 rounded-xl px-3 py-1.5">
                <span className="text-[12px] font-medium text-gray-500">Tax Period:</span>
                <select
                  value={data.selected_period || ""}
                  onChange={(e) => setSelectedPeriod(e.target.value)}
                  className="bg-transparent text-[13px] font-semibold text-gray-900 focus:outline-none cursor-pointer"
                >
                  {periods.map((p) => (
                    <option key={p.period} value={p.period}>
                      {p.period} ({p.status})
                    </option>
                  ))}
                </select>
              </div>
            )}

            {/* Run Status Badge */}
            {run_id && (
              <span
                className={`inline-flex items-center gap-1.5 rounded-full px-3 py-1 text-[11px] font-bold uppercase tracking-wider ${
                  is_locked
                    ? "bg-emerald-100 text-emerald-800 border border-emerald-300"
                    : "bg-amber-100 text-amber-900 border border-amber-300"
                }`}
              >
                <span className={`h-1.5 w-1.5 rounded-full ${is_locked ? "bg-emerald-600" : "bg-amber-600 animate-pulse"}`} />
                {is_locked ? "FINALIZED & LOCKED" : "PROVISIONAL DRAFT"}
              </span>
            )}

            {/* Navigation links */}
            {run_id && (
              <div className="flex items-center gap-2">
                <Link
                  href={`/reconcile/runs/${run_id}/results`}
                  className="inline-flex items-center gap-1 rounded-lg border border-gray-200 bg-white px-3 py-1.5 text-[12px] font-semibold text-gray-700 hover:bg-gray-50 transition"
                >
                  Reconciliation Results →
                </Link>
                <Link
                  href={`/reconcile/runs/${run_id}/gstr3b`}
                  className="inline-flex items-center gap-1 rounded-lg bg-black px-3.5 py-1.5 text-[12px] font-semibold text-white hover:bg-gray-800 transition shadow-xs"
                >
                  Table 4 Workpaper →
                </Link>
              </div>
            )}
          </div>
        </div>

        {/* Audit Hash line if finalized */}
        {audit_hash && (
          <div className="mt-4 pt-3 border-t border-gray-100 flex items-center gap-2 text-[11.5px] text-gray-500">
            <span className="font-medium text-emerald-800">Certified SHA-256 Audit Hash:</span>
            <span className="font-mono bg-gray-50 px-2 py-0.5 rounded border border-gray-200 text-gray-800">
              {audit_hash}
            </span>
          </div>
        )}
      </div>

      {/* 2. Executive ITC KPI Metrics Cards */}
      <div>
        <div className="flex items-center justify-between mb-3">
          <h2 className="text-[14px] font-bold text-gray-900 tracking-tight">
            Authoritative ITC Position
          </h2>
          <span className="text-[11.5px] text-gray-400 font-medium">
            Values sourced from Table 4 statutory engine & reconciliation outcomes
          </span>
        </div>

        <div className="grid grid-cols-2 md:grid-cols-3 lg:grid-cols-6 gap-3">
          {/* Card 1: Eligible ITC */}
          <div className="rounded-xl border border-emerald-200 bg-emerald-50/40 p-4 shadow-xs">
            <p className="text-[11px] font-semibold uppercase tracking-wider text-emerald-800">Eligible ITC (4A5)</p>
            <p className="mt-1.5 font-mono text-[17px] font-bold text-gray-900 tabular-nums">
              {formatINR(kpis.eligible_itc)}
            </p>
            <p className="mt-1 text-[11px] text-emerald-700">Gross domestic eligible credit</p>
          </div>

          {/* Card 2: On Hold */}
          <div className="rounded-xl border border-amber-200 bg-amber-50/40 p-4 shadow-xs">
            <p className="text-[11px] font-semibold uppercase tracking-wider text-amber-900">On Hold</p>
            <p className="mt-1.5 font-mono text-[17px] font-bold text-gray-900 tabular-nums">
              {formatINR(kpis.on_hold_itc)}
            </p>
            <p className="mt-1 text-[11px] text-amber-800">Goods not received / transit</p>
          </div>

          {/* Card 3: At Risk */}
          <div className="rounded-xl border border-rose-200 bg-rose-50/40 p-4 shadow-xs">
            <p className="text-[11px] font-semibold uppercase tracking-wider text-rose-900">At Risk</p>
            <p className="mt-1.5 font-mono text-[17px] font-bold text-gray-900 tabular-nums">
              {formatINR(kpis.at_risk_itc)}
            </p>
            <p className="mt-1 text-[11px] text-rose-700">Wrongful or high discrepancy</p>
          </div>

          {/* Card 4: Missed ITC */}
          <div className="rounded-xl border border-blue-200 bg-blue-50/40 p-4 shadow-xs">
            <p className="text-[11px] font-semibold uppercase tracking-wider text-blue-900">Missed ITC</p>
            <p className="mt-1.5 font-mono text-[17px] font-bold text-gray-900 tabular-nums">
              {formatINR(kpis.missed_itc)}
            </p>
            <p className="mt-1 text-[11px] text-blue-700">PR invoices absent from 2B</p>
          </div>

          {/* Card 5: Reversed */}
          <div className="rounded-xl border border-orange-200 bg-orange-50/40 p-4 shadow-xs">
            <p className="text-[11px] font-semibold uppercase tracking-wider text-orange-900">Reversed (4B)</p>
            <p className="mt-1.5 font-mono text-[17px] font-bold text-gray-900 tabular-nums">
              {formatINR(kpis.reversed_itc)}
            </p>
            <p className="mt-1 text-[11px] text-orange-700">Sec 17(5) + Rule 37 reversals</p>
          </div>

          {/* Card 6: Reclaimed */}
          <div className="rounded-xl border border-indigo-200 bg-indigo-50/40 p-4 shadow-xs">
            <p className="text-[11px] font-semibold uppercase tracking-wider text-indigo-900">Reclaimed (4D1)</p>
            <p className="mt-1.5 font-mono text-[17px] font-bold text-gray-900 tabular-nums">
              {formatINR(kpis.reclaimed_itc)}
            </p>
            <p className="mt-1 text-[11px] text-indigo-700">Paid past 4B2 reversals</p>
          </div>
        </div>
      </div>

      {/* 3. Action Queue: "Needs Attention" */}
      <div className="rounded-2xl border border-gray-200 bg-white overflow-hidden shadow-xs">
        <div className="border-b border-gray-200 px-6 py-4 bg-[#FAFAFA] flex flex-wrap items-center justify-between gap-4">
          <div>
            <div className="flex items-center gap-2">
              <h2 className="text-[16px] font-bold text-gray-900">
                Action Queue — Needs Attention
              </h2>
              <span className="rounded-full bg-black px-2.5 py-0.5 text-[11px] font-bold text-white">
                {summary_counts.total_items}
              </span>
              {summary_counts.blocking_count > 0 && (
                <span className="rounded-full bg-rose-100 border border-rose-300 px-2.5 py-0.5 text-[11px] font-bold text-rose-800 animate-pulse">
                  {summary_counts.blocking_count} Finalize Blocker{summary_counts.blocking_count > 1 ? "s" : ""}
                </span>
              )}
            </div>
            <p className="mt-1 text-[12px] text-gray-500">
              Prioritized operational work items requiring CA verification, vendor communication, or audit disposition.
            </p>
          </div>

          {/* Search Bar */}
          <div className="w-full sm:w-72">
            <input
              type="text"
              placeholder="Search vendor, GSTIN, invoice..."
              value={searchQuery}
              onChange={(e) => setSearchQuery(e.target.value)}
              className="w-full rounded-xl border border-gray-200 bg-white px-3.5 py-1.5 text-[12px] placeholder:text-gray-400 focus:border-black focus:outline-none"
            />
          </div>
        </div>

        {/* Priority Filter Tabs & Exception Dropdown */}
        <div className="border-b border-gray-200 px-6 py-3 flex flex-wrap items-center justify-between gap-3 bg-white text-[12.5px]">
          <div className="flex flex-wrap items-center gap-2 font-medium">
            <button
              onClick={() => setActivePriorityTab("ALL")}
              className={`rounded-lg px-3 py-1 transition ${
                activePriorityTab === "ALL"
                  ? "bg-black text-white font-semibold"
                  : "text-gray-600 hover:bg-gray-100"
              }`}
            >
              All Items ({summary_counts.total_items})
            </button>
            <button
              onClick={() => setActivePriorityTab("BLOCKER")}
              className={`rounded-lg px-3 py-1 transition ${
                activePriorityTab === "BLOCKER"
                  ? "bg-rose-700 text-white font-semibold shadow-xs"
                  : "text-rose-700 hover:bg-rose-50"
              }`}
            >
              Blockers ({summary_counts.blocking_count})
            </button>
            <button
              onClick={() => setActivePriorityTab("CRITICAL")}
              className={`rounded-lg px-3 py-1 transition ${
                activePriorityTab === "CRITICAL"
                  ? "bg-rose-600 text-white font-semibold"
                  : "text-gray-600 hover:bg-gray-100"
              }`}
            >
              Critical ({summary_counts.critical_count})
            </button>
            <button
              onClick={() => setActivePriorityTab("HIGH")}
              className={`rounded-lg px-3 py-1 transition ${
                activePriorityTab === "HIGH"
                  ? "bg-amber-600 text-white font-semibold"
                  : "text-gray-600 hover:bg-gray-100"
              }`}
            >
              High ({summary_counts.high_count})
            </button>
            <button
              onClick={() => setActivePriorityTab("MEDIUM")}
              className={`rounded-lg px-3 py-1 transition ${
                activePriorityTab === "MEDIUM"
                  ? "bg-blue-600 text-white font-semibold"
                  : "text-gray-600 hover:bg-gray-100"
              }`}
            >
              Medium ({summary_counts.medium_count})
            </button>
            <button
              onClick={() => setActivePriorityTab("RESOLVED")}
              className={`rounded-lg px-3 py-1 transition ${
                activePriorityTab === "RESOLVED"
                  ? "bg-emerald-700 text-white font-semibold"
                  : "text-gray-600 hover:bg-gray-100"
              }`}
            >
              Resolved ({summary_counts.resolved_count})
            </button>
          </div>

          <div className="flex items-center gap-2">
            <span className="text-gray-400 text-[11.5px]">Exception Type:</span>
            <select
              value={selectedExceptionType}
              onChange={(e) => setSelectedExceptionType(e.target.value)}
              className="rounded-lg border border-gray-200 bg-white px-2.5 py-1 text-[12px] text-gray-800 focus:outline-none focus:border-black cursor-pointer"
            >
              <option value="">All Categories</option>
              <option value="RULE_37">Rule 37 (&gt;180d)</option>
              <option value="SEC_17_5">Section 17(5)</option>
              <option value="MISSING_2B">Missing in 2B</option>
              <option value="2B_ONLY">2B Only (Unbooked)</option>
              <option value="VALUE_MISMATCH">Value Mismatch</option>
              <option value="RULE_37A">Rule 37A</option>
              <option value="TIME_BARRED_16_4">Sec 16(4) Time-Barred</option>
            </select>
          </div>
        </div>

        {/* Work Item List */}
        {work_items.length === 0 ? (
          <div className="py-20 text-center text-gray-400 text-[13px]">
            No action items matching the selected filters.
          </div>
        ) : (
          <div className="divide-y divide-gray-100">
            {work_items.map((item) => {
              const isExpanded = expandedItemId === item.work_item_id;
              return (
                <div
                  key={item.work_item_id}
                  className={`p-5 transition hover:bg-gray-50/70 ${
                    item.is_blocking ? "bg-rose-50/20" : ""
                  }`}
                >
                  <div className="flex flex-wrap items-start justify-between gap-4">
                    <div className="space-y-1.5 max-w-2xl">
                      <div className="flex flex-wrap items-center gap-2">
                        {/* Priority Badge */}
                        <span
                          className={`rounded-md border px-2 py-0.5 text-[10.5px] font-bold tracking-wider uppercase ${getPriorityBadgeClass(
                            item.priority
                          )}`}
                        >
                          {item.priority}
                        </span>

                        {/* Blocker Badge */}
                        {item.is_blocking && (
                          <span className="rounded-md bg-rose-600 text-white px-2 py-0.5 text-[10.5px] font-bold">
                            Table 4 Blocker
                          </span>
                        )}

                        {/* Exception Category */}
                        <span className="font-mono text-[11px] font-semibold text-gray-600 bg-gray-100 px-2 py-0.5 rounded">
                          {item.exception_type}
                        </span>

                        {/* Status */}
                        <span
                          className={`rounded-full px-2.5 py-0.5 text-[10.5px] font-semibold ${
                            item.status === "RESOLVED"
                              ? "bg-green-100 text-green-800"
                              : item.status === "AWAITING_VENDOR"
                              ? "bg-blue-100 text-blue-800"
                              : item.status === "ACTION_REQUIRED"
                              ? "bg-rose-100 text-rose-800"
                              : "bg-gray-100 text-gray-700"
                          }`}
                        >
                          {item.status}
                        </span>

                        {/* Assignee */}
                        <span className="text-[11px] text-gray-600 bg-gray-100 px-2 py-0.5 rounded flex items-center gap-1">
                          <svg className="h-3 w-3 text-gray-400" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M16 7a4 4 0 11-8 0 4 4 0 018 0zM12 14a7 7 0 00-7 7h14a7 7 0 00-7-7z" />
                          </svg>
                          {item.assigned_to_name || "Unassigned"}
                        </span>

                        {/* SLA Indicator */}
                        {item.sla_status && item.sla_status !== "NO_DUE_DATE" && (
                          <span
                            className={`text-[10px] font-bold px-2 py-0.5 rounded border uppercase tracking-wider ${
                              item.sla_status === "OVERDUE"
                                ? "bg-rose-50 text-rose-700 border-rose-200"
                                : item.sla_status === "DUE_SOON"
                                ? "bg-amber-50 text-amber-700 border-amber-200"
                                : "bg-emerald-50 text-emerald-700 border-emerald-200"
                            }`}
                          >
                            {item.sla_status.replace(/_/g, " ")}
                          </span>
                        )}

                        {/* Age */}
                        {item.age_days > 0 && (
                          <span className="text-[11px] text-gray-400">
                            {item.age_days} days old
                          </span>
                        )}
                      </div>

                      {/* Supplier & Invoice metadata */}
                      <div className="flex flex-wrap items-baseline gap-2 pt-0.5">
                        <span className="font-bold text-[14px] text-gray-900">
                          {item.supplier_name}
                        </span>
                        <span className="font-mono text-[11.5px] text-gray-500">
                          {item.supplier_gstin}
                        </span>
                        <span className="text-gray-300">•</span>
                        <span className="text-[12.5px] font-medium text-gray-700">
                          Inv #{item.invoice_number}
                        </span>
                        {item.invoice_date && (
                          <>
                            <span className="text-gray-300">•</span>
                            <span className="text-[12px] text-gray-500">{item.invoice_date}</span>
                          </>
                        )}
                      </div>
                    </div>

                    {/* ITC Impact & Action CTAs */}
                    <div className="flex flex-col items-end gap-2">
                      <div className="text-right">
                        <span className="text-[10.5px] font-semibold text-gray-400 uppercase tracking-wider block">
                          ITC Impact
                        </span>
                        <span className="font-mono text-[16px] font-bold text-gray-900 tabular-nums">
                          {formatINR(item.itc_impact)}
                        </span>
                      </div>

                      <div className="flex items-center gap-2">
                        {/* Phase 5.2 Workflow Drawer Trigger */}
                        <button
                          type="button"
                          onClick={() => setSelectedDetailItem(item)}
                          className="rounded-lg bg-black px-3 py-1.5 text-[11.5px] font-semibold text-white hover:bg-gray-800 transition cursor-pointer shadow-xs"
                        >
                          Workflow &amp; History →
                        </button>

                        {/* Resolve Exception Button for Blockers */}
                        {item.is_blocking && !is_locked && (
                          <button
                            type="button"
                            onClick={() => handleOpenDisposition(item)}
                            className="inline-flex items-center gap-1.5 rounded-lg bg-rose-700 px-3 py-1.5 text-[11.5px] font-semibold text-white hover:bg-rose-800 shadow-xs transition cursor-pointer"
                          >
                            <span className="h-1.5 w-1.5 rounded-full bg-rose-300 animate-pulse" />
                            Resolve Blocker
                          </button>
                        )}

                        {/* WHAT/WHY/NEXT Accordion Toggle */}
                        <button
                          type="button"
                          onClick={() => setExpandedItemId(isExpanded ? null : item.work_item_id)}
                          className="rounded-lg border border-gray-200 bg-white px-2.5 py-1.5 text-[11.5px] font-medium text-gray-700 hover:bg-gray-100 transition cursor-pointer"
                        >
                          {isExpanded ? "Hide Guidance ▲" : "View Guidance ▼"}
                        </button>
                      </div>
                    </div>
                  </div>

                  {/* Expandable WHAT / WHY / NEXT Section */}
                  {isExpanded && (
                    <div className="mt-4 rounded-xl border border-gray-200 bg-[#F9FAFB] p-4 text-[12.5px] space-y-3 animate-in fade-in duration-150">
                      <div>
                        <span className="font-bold text-gray-900 uppercase tracking-wider text-[11px] block">
                          WHAT Happened
                        </span>
                        <p className="mt-0.5 text-gray-700">{item.what}</p>
                      </div>

                      <div>
                        <span className="font-bold text-gray-900 uppercase tracking-wider text-[11px] block">
                          WHY (Evidence & Context)
                        </span>
                        <p className="mt-0.5 text-gray-700">{item.why}</p>
                      </div>

                      <div>
                        <span className="font-bold text-blue-900 uppercase tracking-wider text-[11px] block">
                          NEXT (Recommended CA Operational Action)
                        </span>
                        <p className="mt-0.5 text-blue-950 font-medium">{item.next_action}</p>
                      </div>

                      {item.disposition && (
                        <div className="border-t border-gray-200 pt-2 text-[12px] flex items-center gap-2">
                          <span className="font-bold text-emerald-800">Recorded Disposition:</span>
                          <span className="font-mono bg-white px-2 py-0.5 rounded border border-gray-200 text-gray-800">
                            {item.disposition}
                          </span>
                          {item.disposition_reason && (
                            <span className="text-gray-500 italic">— {item.disposition_reason}</span>
                          )}
                        </div>
                      )}
                    </div>
                  )}
                </div>
              );
            })}
          </div>
        )}
      </div>

      {/* Phase 5.2 Work Item Detail Drawer */}
      {selectedDetailItem && (
        <ItcWorkItemDetailDrawer
          workItem={selectedDetailItem}
          authToken={authToken}
          clientId={clientId}
          onClose={() => setSelectedDetailItem(null)}
          onUpdated={() => {
            mutate();
            void swrMutate((key) => Array.isArray(key) && key[0] === "itc-command-center");
            void swrMutate((key) => Array.isArray(key) && key[0] === "work-item");
          }}
        />
      )}

      {/* Disposition Modal for direct resolution from Command Center */}
      {targetDispositionRecord && run_id && (
        <Table4DispositionModal
          runId={run_id}
          authToken={authToken}
          isOpen={!is_locked && isDispositionModalOpen}
          targetRecord={targetDispositionRecord}
          onClose={() => {
            setIsDispositionModalOpen(false);
            setTargetDispositionRecord(null);
          }}
          onSuccess={(disp) => {
            mutate();
            void swrMutate((key) => Array.isArray(key) && key[0] === "table4-workpaper");
            void swrMutate((key) => Array.isArray(key) && key[0] === "table4-drilldown");
            setIsDispositionModalOpen(false);
            setTargetDispositionRecord(null);
            setActionSuccessMsg(`Exception disposition (${disp || "RESOLVED"}) recorded successfully.`);
            setTimeout(() => setActionSuccessMsg(null), 5000);
          }}
        />
      )}
    </div>
  );
}
