"use client";

import { useMemo, useState } from "react";
import useSWR from "swr";
import {
  reversalLedgerApi,
  type ReversalLedgerEntryDto,
  type ReversalLedgerRunResponse,
  type ReversalLedgerClientResponse,
  type ClientReclaimableBalancesResponse,
  type ReversalStatusType,
} from "@/lib/api";
import { formatINR } from "@/lib/format";
import {
  REVERSAL_STATUS_META,
  STATUTORY_REASON_LABELS,
  canAuthorizeReclaim,
  canExecuteReclaim,
  canFulfillCondition,
  paiseToRupees,
} from "./reversalLedgerLogic";
import { ReversalEvidenceModal } from "./ReversalEvidenceModal";
import { ReversalAuthorizeModal } from "./ReversalAuthorizeModal";
import { ReversalReclaimModal } from "./ReversalReclaimModal";
import { ReversalAuditDrawer } from "./ReversalAuditDrawer";

interface ReversalReclaimLedgerViewProps {
  mode: "run" | "client";
  runId?: string;
  clientId?: string;
  authToken: string;
  onReclaimSuccess?: () => void;
  availableTargetRuns?: Array<{ id: string; period: string; is_locked: boolean; status: string }>;
}

export function ReversalReclaimLedgerView({
  mode,
  runId,
  clientId,
  authToken,
  onReclaimSuccess,
  availableTargetRuns = [],
}: ReversalReclaimLedgerViewProps) {
  const [selectedStatusFilter, setSelectedStatusFilter] = useState<string>("ALL");
  const [selectedReasonFilter, setSelectedReasonFilter] = useState<string>("ALL");
  const [searchQuery, setSearchQuery] = useState<string>("");

  // Modal states
  const [evidenceEntry, setEvidenceEntry] = useState<ReversalLedgerEntryDto | null>(null);
  const [authorizeEntry, setAuthorizeEntry] = useState<ReversalLedgerEntryDto | null>(null);
  const [reclaimEntry, setReclaimEntry] = useState<ReversalLedgerEntryDto | null>(null);
  const [auditEntry, setAuditEntry] = useState<ReversalLedgerEntryDto | null>(null);

  // Run view SWR
  const {
    data: runData,
    isLoading: isRunLoading,
    error: runError,
    mutate: mutateRun,
  } = useSWR<ReversalLedgerRunResponse>(
    mode === "run" && authToken && runId ? [`run-reversal-ledger`, runId] : null,
    () => reversalLedgerApi.getRunReversalLedger(authToken, runId!),
    { refreshInterval: 0 }
  );

  // Client view SWR
  const resolvedClientId = clientId || runData?.client_gstin_id;
  const {
    data: clientData,
    isLoading: isClientLoading,
    error: clientError,
    mutate: mutateClient,
  } = useSWR<ReversalLedgerClientResponse>(
    mode === "client" && authToken && resolvedClientId
      ? [`client-reversal-ledger`, resolvedClientId, selectedStatusFilter, selectedReasonFilter]
      : null,
    () =>
      reversalLedgerApi.getClientReversalLedger(authToken, resolvedClientId!, {
        status: selectedStatusFilter !== "ALL" ? selectedStatusFilter : undefined,
        statutory_reason: selectedReasonFilter !== "ALL" ? selectedReasonFilter : undefined,
      }),
    { refreshInterval: 0 }
  );

  // Client Reclaimable Balances SWR
  const {
    data: balanceData,
    mutate: mutateBalances,
  } = useSWR<ClientReclaimableBalancesResponse>(
    authToken && resolvedClientId ? [`client-reclaimable-balances`, resolvedClientId] : null,
    () => reversalLedgerApi.getClientReclaimableBalances(authToken, resolvedClientId!),
    { refreshInterval: 0 }
  );

  const rawItems: ReversalLedgerEntryDto[] = useMemo(() => {
    if (mode === "run") return runData?.items || [];
    return clientData?.items || [];
  }, [mode, runData, clientData]);

  // Client-side filtering for run mode (or refinement for client mode)
  const filteredItems = useMemo(() => {
    return rawItems.filter((item) => {
      if (selectedStatusFilter !== "ALL" && item.status !== selectedStatusFilter) {
        return false;
      }
      if (selectedReasonFilter !== "ALL" && item.statutory_reason !== selectedReasonFilter) {
        return false;
      }
      if (searchQuery.trim()) {
        const q = searchQuery.toLowerCase().trim();
        const docMatch = (item.document_number || "").toLowerCase().includes(q);
        const gstinMatch = (item.supplier_gstin || "").toLowerCase().includes(q);
        const nameMatch = (item.supplier_legal_name || "").toLowerCase().includes(q);
        if (!docMatch && !gstinMatch && !nameMatch) return false;
      }
      return true;
    });
  }, [rawItems, selectedStatusFilter, selectedReasonFilter, searchQuery]);

  const handleMutation = () => {
    if (mode === "run") mutateRun();
    if (mode === "client") mutateClient();
    mutateBalances();
    if (onReclaimSuccess) onReclaimSuccess();
  };

  const isLoading = mode === "run" ? isRunLoading : isClientLoading;
  const loadError = mode === "run" ? runError : clientError;

  if (isLoading && !rawItems.length) {
    return (
      <div className="flex flex-col items-center justify-center py-16 gap-3">
        <svg className="h-7 w-7 animate-spin text-black" fill="none" viewBox="0 0 24 24">
          <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
          <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8v8z" />
        </svg>
        <p className="text-[13px] text-gray-500">Loading Table 4 Reversal & Reclaim Ledger…</p>
      </div>
    );
  }

  if (loadError) {
    return (
      <div className="rounded-xl border border-red-200 bg-red-50 p-6 text-center">
        <p className="text-[13.5px] font-semibold text-red-800">
          Failed to load Table 4 Reversal Ledger
        </p>
        <p className="mt-1 text-[12px] text-red-600">
          {loadError?.detail || loadError?.message || "Please refresh or verify access permissions."}
        </p>
      </div>
    );
  }

  const authorizedTotalPaise =
    balanceData?.total_reclaimable_authorized?.total_paise ??
    balanceData?.total_authorized_reclaim_paise ??
    0;
  const pendingTotalPaise =
    balanceData?.total_pending_authorization?.total_paise ??
    balanceData?.total_pending_reclaim_paise ??
    0;

  const totalReversedPaise =
    mode === "run"
      ? runData?.summary?.reversed?.total_paise ?? runData?.total_reversed_paise ?? 0
      : clientData?.summary?.reversed?.total_paise ?? clientData?.total_reversed_paise ?? 0;

  const totalReclaimedPaise =
    mode === "run"
      ? runData?.summary?.reclaimed?.total_paise ?? runData?.total_reclaimed_paise ?? 0
      : clientData?.summary?.reclaimed?.total_paise ?? clientData?.total_reclaimed_paise ?? 0;

  return (
    <div className="space-y-5">
      {/* Top Metric Cards */}
      <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-4">
        {/* Total Ledger Reversals */}
        <div className="rounded-2xl border border-[#E5E7EB] bg-white p-4 shadow-sm">
          <div className="text-[11px] font-bold text-gray-400 uppercase tracking-wider">
            {mode === "run" ? "Period Reversals" : "Total Reversals Recorded"}
          </div>
          <div className="mt-1.5 font-mono text-[20px] font-bold text-gray-900 tabular-nums">
            {formatINR(paiseToRupees(totalReversedPaise))}
          </div>
          <div className="mt-1 text-[11.5px] text-gray-500">
            {mode === "run" ? runData?.total_count || 0 : clientData?.total_count || 0} entries in Table 4(B)(2)
          </div>
        </div>

        {/* Pending Condition Fulfillment */}
        <div className="rounded-2xl border border-amber-200 bg-amber-50/50 p-4 shadow-sm">
          <div className="text-[11px] font-bold text-amber-800 uppercase tracking-wider">
            Condition Pending
          </div>
          <div className="mt-1.5 font-mono text-[20px] font-bold text-amber-950 tabular-nums">
            {formatINR(paiseToRupees(pendingTotalPaise))}
          </div>
          <div className="mt-1 text-[11.5px] text-amber-800">
            Awaiting 180-day payment / GSTR-3B filing proof
          </div>
        </div>

        {/* Authorized Reclaimable Balance */}
        <div className="rounded-2xl border border-emerald-200 bg-emerald-50/60 p-4 shadow-sm">
          <div className="text-[11px] font-bold text-emerald-800 uppercase tracking-wider">
            Authorized Reclaimable
          </div>
          <div className="mt-1.5 font-mono text-[20px] font-bold text-emerald-950 tabular-nums">
            {formatINR(paiseToRupees(authorizedTotalPaise))}
          </div>
          <div className="mt-1 text-[11.5px] text-emerald-800">
            {(balanceData?.items?.filter(
              (i) => i.status === "RECLAIM_AUTHORIZED" || i.status === "PARTIALLY_RECLAIMED"
            ).length ?? balanceData?.authorized_reclaimable_records ?? 0)}{" "}
            records ready to reclaim in 3B
          </div>
        </div>

        {/* Historical Reclaimed */}
        <div className="rounded-2xl border border-[#E5E7EB] bg-white p-4 shadow-sm">
          <div className="text-[11px] font-bold text-gray-400 uppercase tracking-wider">
            Historical Reclaimed
          </div>
          <div className="mt-1.5 font-mono text-[20px] font-bold text-indigo-900 tabular-nums">
            {formatINR(paiseToRupees(totalReclaimedPaise))}
          </div>
          <div className="mt-1 text-[11.5px] text-gray-500">
            Credited via Table 4(A)(5) & Table 4(D)(1)
          </div>
        </div>
      </div>

      {/* Authorized Reclaimable Banner Alert for Active Runs */}
      {mode === "run" && authorizedTotalPaise > 0 && (
        <div className="rounded-xl border border-emerald-300 bg-emerald-50 p-4 flex flex-wrap items-center justify-between gap-3">
          <div className="flex items-center gap-2.5">
            <span className="h-3 w-3 rounded-full bg-emerald-600 animate-ping" />
            <div>
              <p className="text-[13px] font-bold text-emerald-950">
                Authorized Reclaims Available: {formatINR(paiseToRupees(authorizedTotalPaise))}
              </p>
              <p className="text-[12px] text-emerald-800">
                You have verified reclaims from earlier tax periods ready to be claimed into this return [Table 4(A)(5) and 4(D)(1)].
              </p>
            </div>
          </div>
          <button
            onClick={() => {
              // Filter to authorized entries
              setSelectedStatusFilter("RECLAIM_AUTHORIZED");
            }}
            className="rounded-lg bg-emerald-800 px-3.5 py-1.5 text-[12px] font-semibold text-white hover:bg-emerald-900 transition"
          >
            Review Reclaimable Balances
          </button>
        </div>
      )}

      {/* Filter and Search Controls */}
      <div className="flex flex-wrap items-center justify-between gap-3 rounded-xl border border-[#E5E7EB] bg-[#FAFAFA] p-3">
        <div className="flex flex-wrap items-center gap-2 text-[12px]">
          {/* Status Filter */}
          <select
            value={selectedStatusFilter}
            onChange={(e) => setSelectedStatusFilter(e.target.value)}
            className="rounded-lg border border-gray-300 bg-white px-2.5 py-1.5 text-gray-800 font-medium focus:border-black focus:outline-none"
          >
            <option value="ALL">All Lifecycle Statuses</option>
            <option value="OPEN">Condition Pending</option>
            <option value="CONDITION_FULFILLED">Condition Verified (Awaiting CA Signoff)</option>
            <option value="RECLAIM_AUTHORIZED">Reclaim Authorized</option>
            <option value="PARTIALLY_RECLAIMED">Partially Reclaimed</option>
            <option value="FULLY_RECLAIMED">Fully Reclaimed</option>
            <option value="NON_RECLAIMABLE">Non-Reclaimable</option>
          </select>

          {/* Statutory Category Filter */}
          <select
            value={selectedReasonFilter}
            onChange={(e) => setSelectedReasonFilter(e.target.value)}
            className="rounded-lg border border-gray-300 bg-white px-2.5 py-1.5 text-gray-800 font-medium focus:border-black focus:outline-none"
          >
            <option value="ALL">All Statutory Reasons</option>
            <option value="RULE_37_NON_PAYMENT">Rule 37 (180-Day Payment)</option>
            <option value="RULE_37A_SUPPLIER_NON_FILING">Rule 37A (Supplier 3B)</option>
            <option value="SECTION_16_2_B_NOT_RECEIVED">Section 16(2)(b) (Receipt)</option>
            <option value="SECTION_16_2_C_SUPPLIER_TAX_CONDITION">Section 16(2)(c) (Tax Paid)</option>
            <option value="OTHER_TEMPORARY">Other Temporary</option>
          </select>
        </div>

        {/* Search Input */}
        <div className="relative min-w-[240px]">
          <input
            type="text"
            placeholder="Search invoice, GSTIN, supplier…"
            value={searchQuery}
            onChange={(e) => setSearchQuery(e.target.value)}
            className="w-full rounded-lg border border-gray-300 px-3 py-1.5 text-[12.5px] text-gray-900 focus:border-black focus:outline-none"
          />
        </div>
      </div>

      {/* Ledger Table */}
      <div className="rounded-2xl border border-[#E5E7EB] bg-white overflow-hidden shadow-sm">
        <div className="overflow-x-auto">
          <table className="w-full text-left border-collapse text-[12.5px]">
            <thead className="bg-[#F8FAFC] text-[11px] font-bold text-gray-500 uppercase tracking-wider border-b border-[#E5E7EB]">
              <tr>
                <th className="px-4 py-3">Document & Supplier</th>
                <th className="px-3 py-3">Source Period</th>
                <th className="px-4 py-3">Statutory Category</th>
                <th className="px-3 py-3 text-right">Reversed Tax</th>
                <th className="px-3 py-3 text-right">Outstanding</th>
                <th className="px-4 py-3">Lifecycle Status</th>
                <th className="px-4 py-3 text-right">Workflow Action</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-gray-100">
              {filteredItems.length === 0 ? (
                <tr>
                  <td colSpan={7} className="px-4 py-12 text-center text-gray-400">
                    No reversal records match the selected filters.
                  </td>
                </tr>
              ) : (
                filteredItems.map((item) => {
                  const statusMeta = REVERSAL_STATUS_META[item.status] || {
                    label: item.status,
                    badgeBg: "bg-gray-100",
                    badgeText: "text-gray-800",
                    badgeBorder: "border-gray-200",
                    dotColor: "bg-gray-400",
                  };

                  const totalRevPaise =
                    item.reversed_total_tax_paise ??
                    ((item.reversed_igst_paise || 0) +
                      (item.reversed_cgst_paise || 0) +
                      (item.reversed_sgst_paise || 0) +
                      (item.reversed_cess_paise || 0));

                  const cachedRecPaise =
                    (item.cached_reclaimed_igst_paise || 0) +
                    (item.cached_reclaimed_cgst_paise || 0) +
                    (item.cached_reclaimed_sgst_paise || 0) +
                    (item.cached_reclaimed_cess_paise || 0);

                  const flatRecPaise =
                    (item.reclaimed_igst_paise || 0) +
                    (item.reclaimed_cgst_paise || 0) +
                    (item.reclaimed_sgst_paise || 0) +
                    (item.reclaimed_cess_paise || 0);

                  const totalRecPaise =
                    item.reclaimed_total_tax_paise ?? (cachedRecPaise || flatRecPaise);

                  const reversedRupees = paiseToRupees(totalRevPaise);
                  const reclaimedRupees = paiseToRupees(totalRecPaise);
                  const outstandingRupees =
                    item.remaining_balances_paise?.total != null
                      ? paiseToRupees(item.remaining_balances_paise.total)
                      : Math.max(0, reversedRupees - reclaimedRupees);

                  return (
                    <tr key={item.id} className="hover:bg-gray-50/60 transition">
                      {/* Document & Supplier */}
                      <td className="px-4 py-3">
                        <div className="font-mono font-bold text-gray-900">
                          {item.document_number}
                        </div>
                        <div className="text-[11.5px] text-gray-500 flex items-center gap-1">
                          <span className="font-mono">{item.supplier_gstin}</span>
                          {item.supplier_legal_name && (
                            <span className="truncate max-w-[160px]">
                              • {item.supplier_legal_name}
                            </span>
                          )}
                        </div>
                      </td>

                      {/* Source Period */}
                      <td className="px-3 py-3 whitespace-nowrap">
                        <span className="rounded bg-gray-100 px-2 py-0.5 font-mono text-[11.5px] font-medium text-gray-700">
                          {item.reversal_tax_period}
                        </span>
                      </td>

                      {/* Statutory Category */}
                      <td className="px-4 py-3 max-w-[220px]">
                        <span className="text-gray-800 font-medium block">
                          {STATUTORY_REASON_LABELS[item.statutory_reason] || item.statutory_reason}
                        </span>
                        {item.condition_fulfilled_at && (
                          <span className="text-[10.5px] text-blue-700 block mt-0.5">
                            ✓ Evidence on record
                          </span>
                        )}
                      </td>

                      {/* Reversed Tax */}
                      <td className="px-3 py-3 text-right font-mono tabular-nums text-gray-900 font-semibold">
                        {formatINR(reversedRupees)}
                      </td>

                      {/* Outstanding */}
                      <td className="px-3 py-3 text-right font-mono tabular-nums font-bold text-indigo-900">
                        {formatINR(outstandingRupees)}
                      </td>

                      {/* Lifecycle Status Badge */}
                      <td className="px-4 py-3 whitespace-nowrap">
                        <span
                          className={`inline-flex items-center gap-1.5 rounded-full px-2.5 py-0.5 text-[11px] font-semibold border ${statusMeta.badgeBg} ${statusMeta.badgeText} ${statusMeta.badgeBorder}`}
                        >
                          <span className={`h-1.5 w-1.5 rounded-full ${statusMeta.dotColor}`} />
                          {statusMeta.label}
                        </span>
                      </td>

                      {/* Workflow Actions */}
                      <td className="px-4 py-3 text-right whitespace-nowrap">
                        <div className="inline-flex items-center gap-1.5 justify-end">
                          {/* 1. Fulfill Condition (OPEN) */}
                          {canFulfillCondition(item) && (
                            <button
                              onClick={() => setEvidenceEntry(item)}
                              className="rounded border border-blue-200 bg-blue-50 px-2.5 py-1 text-[11.5px] font-semibold text-blue-800 hover:bg-blue-100 transition"
                            >
                              Submit Evidence
                            </button>
                          )}

                          {/* 2. Authorize Reclaim (CONDITION_FULFILLED) */}
                          {canAuthorizeReclaim(item) && (
                            <button
                              onClick={() => setAuthorizeEntry(item)}
                              className="rounded border border-emerald-300 bg-emerald-50 px-2.5 py-1 text-[11.5px] font-semibold text-emerald-800 hover:bg-emerald-100 transition"
                            >
                              Authorize Reclaim
                            </button>
                          )}

                          {/* 3. Reclaim into Run (RECLAIM_AUTHORIZED / PARTIALLY_RECLAIMED) */}
                          {canExecuteReclaim(item) && (
                            <button
                              onClick={() => setReclaimEntry(item)}
                              className="rounded bg-black px-2.5 py-1 text-[11.5px] font-semibold text-white hover:bg-gray-800 transition"
                            >
                              Reclaim ITC →
                            </button>
                          )}

                          {/* Non-reclaimable Indicator */}
                          {(!item.is_reclaimable || item.status === "NON_RECLAIMABLE") && (
                            <span className="rounded bg-gray-100 px-2 py-0.5 text-[11px] font-medium text-gray-500 italic">
                              Locked (Permanent)
                            </span>
                          )}

                          {/* Audit Provenance Drawer Button */}
                          <button
                            onClick={() => setAuditEntry(item)}
                            className="rounded border border-gray-200 bg-white p-1 text-gray-500 hover:text-black hover:border-black transition"
                            title="View complete audit provenance"
                          >
                            <svg className="w-3.5 h-3.5" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M13 16h-1v-4h-1m1-4h.01M21 12a9 9 0 11-18 0 9 9 0 0118 0z" />
                            </svg>
                          </button>
                        </div>
                      </td>
                    </tr>
                  );
                })
              )}
            </tbody>
          </table>
        </div>
      </div>

      {/* Modals & Slide-Overs */}
      <ReversalEvidenceModal
        isOpen={Boolean(evidenceEntry)}
        onClose={() => setEvidenceEntry(null)}
        onSuccess={() => handleMutation()}
        entry={evidenceEntry}
        runId={runId || evidenceEntry?.source_run_id || ""}
        authToken={authToken}
      />

      <ReversalAuthorizeModal
        isOpen={Boolean(authorizeEntry)}
        onClose={() => setAuthorizeEntry(null)}
        onSuccess={() => handleMutation()}
        entry={authorizeEntry}
        runId={runId || authorizeEntry?.source_run_id || ""}
        authToken={authToken}
      />

      <ReversalReclaimModal
        isOpen={Boolean(reclaimEntry)}
        onClose={() => setReclaimEntry(null)}
        onSuccess={() => handleMutation()}
        entry={reclaimEntry}
        targetRuns={availableTargetRuns}
        defaultTargetRunId={runId}
        authToken={authToken}
      />

      <ReversalAuditDrawer
        entry={auditEntry}
        onClose={() => setAuditEntry(null)}
      />
    </div>
  );
}
