"use client";

import { useState } from "react";
import useSWR, { mutate as swrMutate } from "swr";
import { formatINR } from "@/lib/format";
import {
  gstr3bApi,
  reconcileRunsApi,
  Gstr3bTable4WorkpaperResponse,
  Table4RowData,
  Table4BlockingRecordItem,
} from "@/lib/api";
import { Table4DrilldownDrawer } from "./Table4DrilldownDrawer";
import { Table4AdjustmentModal } from "./Table4AdjustmentModal";
import { Table4DispositionModal } from "./Table4DispositionModal";
import { ReversalReclaimLedgerView } from "./ReversalReclaimLedgerView";
import { revalidateReconciliationRun } from "@/lib/swrReconciliationSync";

interface Table4WorkpaperViewProps {
  runId: string;
  authToken: string;
  onFinalizeSuccess?: () => void;
}

export function Table4WorkpaperView({
  runId,
  authToken,
  onFinalizeSuccess,
}: Table4WorkpaperViewProps) {
  const [activeDrilldownRow, setActiveDrilldownRow] = useState<string | null>(null);
  const [activeDrilldownLabel, setActiveDrilldownLabel] = useState<string>("");
  const [isAdjustmentModalOpen, setIsAdjustmentModalOpen] = useState(false);
  const [isDispositionModalOpen, setIsDispositionModalOpen] = useState(false);
  const [dispositionTargetRecord, setDispositionTargetRecord] = useState<Table4BlockingRecordItem | null>(null);
  const [isFinalizeModalOpen, setIsFinalizeModalOpen] = useState(false);
  const [isFinalizing, setIsFinalizing] = useState(false);
  const [finalizeError, setFinalizeError] = useState<string | null>(null);
  const [copiedCell, setCopiedCell] = useState<string | null>(null);
  const [actionSuccessMsg, setActionSuccessMsg] = useState<string | null>(null);
  const [activeTab, setActiveTab] = useState<"workpaper" | "reversals">("workpaper");

  const handleOpenDispositionForRecord = (record: Table4BlockingRecordItem) => {
    setDispositionTargetRecord(record);
    setIsDispositionModalOpen(true);
  };

  const { data, error, isLoading, mutate } = useSWR<Gstr3bTable4WorkpaperResponse>(
    authToken && runId ? [`table4-workpaper`, runId] : null,
    () => gstr3bApi.getTable4Workpaper(authToken, runId),
    { refreshInterval: 0 }
  );

  const handleFinalize = async () => {
    if (!runId || !authToken || isFinalizing) return;
    setIsFinalizing(true);
    setFinalizeError(null);
    try {
      await reconcileRunsApi.finalizeRun(authToken, runId);
      await mutate();
      void swrMutate([`run-summary`, runId]);
      void swrMutate([`recon-runs`]);
      onFinalizeSuccess?.();
      setIsFinalizeModalOpen(false);
      setActionSuccessMsg("GSTR-3B Table 4 Workpaper finalized and locked successfully.");
      setTimeout(() => setActionSuccessMsg(null), 5000);
    } catch (err: any) {
      const msg =
        err?.detail ||
        err?.message ||
        "Failed to finalize workpaper. Please try again.";
      setFinalizeError(msg);
    } finally {
      setIsFinalizing(false);
    }
  };

  const copyToClipboard = (text: string, cellKey: string) => {
    navigator.clipboard.writeText(text);
    setCopiedCell(cellKey);
    setTimeout(() => setCopiedCell(null), 2000);
  };

  const copyAllValues = () => {
    if (!data) return;
    const rowTotal = (r: Table4RowData) =>
      r.total_tax !== undefined && r.total_tax !== null
        ? r.total_tax
        : (r.igst || 0) + (r.cgst || 0) + (r.sgst || 0) + (r.cess || 0);

    const summary = [
      `GSTR-3B TABLE 4 WORKPAPER — ${data.client_gstin} (${data.tax_period})`,
      `Status: ${data.status} | Audit Hash: ${data.audit_hash || "N/A"}`,
      `---------------------------------------------------------------------------------`,
      `Row | Description | IGST | CGST | SGST | Cess | Total`,
      `4A1 | Import of Goods | ${t4.section_4a.row_4a1_import_goods.igst} | 0 | 0 | ${t4.section_4a.row_4a1_import_goods.cess} | ${rowTotal(t4.section_4a.row_4a1_import_goods)}`,
      `4A2 | Import of Services | ${t4.section_4a.row_4a2_import_services.igst} | 0 | 0 | ${t4.section_4a.row_4a2_import_services.cess} | ${rowTotal(t4.section_4a.row_4a2_import_services)}`,
      `4A3 | Inward RCM | ${t4.section_4a.row_4a3_inward_rcm.igst} | ${t4.section_4a.row_4a3_inward_rcm.cgst} | ${t4.section_4a.row_4a3_inward_rcm.sgst} | ${t4.section_4a.row_4a3_inward_rcm.cess} | ${rowTotal(t4.section_4a.row_4a3_inward_rcm)}`,
      `4A4 | ISD | ${t4.section_4a.row_4a4_isd.igst} | ${t4.section_4a.row_4a4_isd.cgst} | ${t4.section_4a.row_4a4_isd.sgst} | ${t4.section_4a.row_4a4_isd.cess} | ${rowTotal(t4.section_4a.row_4a4_isd)}`,
      `4A5 | All other ITC | ${t4.section_4a.row_4a5_all_other_itc.igst} | ${t4.section_4a.row_4a5_all_other_itc.cgst} | ${t4.section_4a.row_4a5_all_other_itc.sgst} | ${t4.section_4a.row_4a5_all_other_itc.cess} | ${rowTotal(t4.section_4a.row_4a5_all_other_itc)}`,
      `4A  | Total ITC Available | ${t4.section_4a.total_4a.igst} | ${t4.section_4a.total_4a.cgst} | ${t4.section_4a.total_4a.sgst} | ${t4.section_4a.total_4a.cess} | ${rowTotal(t4.section_4a.total_4a)}`,
      `4B1 | Rules 38,42,43 & 17(5) | ${t4.section_4b.row_4b1_rule38_42_43_sec175.igst} | ${t4.section_4b.row_4b1_rule38_42_43_sec175.cgst} | ${t4.section_4b.row_4b1_rule38_42_43_sec175.sgst} | ${t4.section_4b.row_4b1_rule38_42_43_sec175.cess} | ${rowTotal(t4.section_4b.row_4b1_rule38_42_43_sec175)}`,
      `4B2 | Others (Rule 37, 37A) | ${t4.section_4b.row_4b2_others_rule37_37a.igst} | ${t4.section_4b.row_4b2_others_rule37_37a.cgst} | ${t4.section_4b.row_4b2_others_rule37_37a.sgst} | ${t4.section_4b.row_4b2_others_rule37_37a.cess} | ${rowTotal(t4.section_4b.row_4b2_others_rule37_37a)}`,
      `4B  | Total ITC Reversed | ${t4.section_4b.total_4b.igst} | ${t4.section_4b.total_4b.cgst} | ${t4.section_4b.total_4b.sgst} | ${t4.section_4b.total_4b.cess} | ${rowTotal(t4.section_4b.total_4b)}`,
      `4C  | Net ITC Available | ${t4.section_4c_net_itc.igst} | ${t4.section_4c_net_itc.cgst} | ${t4.section_4c_net_itc.sgst} | ${t4.section_4c_net_itc.cess} | ${rowTotal(t4.section_4c_net_itc)}`,
      `4D1 | Reclaimed ITC | ${t4.section_4d.row_4d1_reclaimed.igst} | ${t4.section_4d.row_4d1_reclaimed.cgst} | ${t4.section_4d.row_4d1_reclaimed.sgst} | ${t4.section_4d.row_4d1_reclaimed.cess} | ${rowTotal(t4.section_4d.row_4d1_reclaimed)}`,
      `4D2 | Ineligible 16(4) & POS | ${t4.section_4d.row_4d2_ineligible_16_4_pos.igst} | ${t4.section_4d.row_4d2_ineligible_16_4_pos.cgst} | ${t4.section_4d.row_4d2_ineligible_16_4_pos.sgst} | ${t4.section_4d.row_4d2_ineligible_16_4_pos.cess} | ${rowTotal(t4.section_4d.row_4d2_ineligible_16_4_pos)}`,
      `---------------------------------------------------------------------------------`,
      `Disclaimer: ${data.disclaimer}`,
    ].join("\n");
    copyToClipboard(summary, "all");
    setActionSuccessMsg("Table 4 summary copied to clipboard!");
    setTimeout(() => setActionSuccessMsg(null), 3000);
  };

  const copyJson = () => {
    if (!data) return;
    copyToClipboard(JSON.stringify(data.table_4, null, 2), "json");
    setActionSuccessMsg("Table 4 JSON copied to clipboard!");
    setTimeout(() => setActionSuccessMsg(null), 3000);
  };

  const openDrilldown = (rowId: string, label: string) => {
    setActiveDrilldownRow(rowId);
    setActiveDrilldownLabel(label);
  };

  if (isLoading && !data) {
    return (
      <div className="flex flex-col items-center justify-center py-24 gap-3">
        <svg className="h-8 w-8 animate-spin text-black" fill="none" viewBox="0 0 24 24">
          <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
          <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8v8z" />
        </svg>
        <p className="text-[13px] text-gray-500">Compiling Table 4 Workpaper…</p>
      </div>
    );
  }

  if (error || !data) {
    return (
      <div className="rounded-xl border border-red-200 bg-red-50 p-6 text-center">
        <p className="text-[14px] font-semibold text-red-800">
          Failed to load GSTR-3B Table 4 Workpaper
        </p>
        <p className="mt-1 text-[12px] text-red-600">
          {error?.detail || error?.message || "Please refresh the page or retry."}
        </p>
      </div>
    );
  }

  const isFinalized = data.status === "FINALIZED";
  const gate = data.gate_audit;
  const t4 = data.table_4;

  const renderCell = (amount: number, rowKey: string, head: string) => {
    const key = `${rowKey}-${head}`;
    const isCopied = copiedCell === key;
    return (
      <td
        className="px-4 py-2.5 text-right font-mono text-[12.5px] tabular-nums text-gray-900 group cursor-pointer hover:bg-gray-100/80 transition relative"
        onClick={() => copyToClipboard(String(amount), key)}
        title="Click to copy exact amount"
      >
        <span className={amount < 0 ? "text-red-600 font-medium" : ""}>
          {amount !== 0 ? formatINR(amount) : "0.00"}
        </span>
        {isCopied && (
          <span className="absolute right-1 -top-2 rounded bg-black px-1.5 py-0.5 text-[9px] font-bold text-white shadow">
            Copied!
          </span>
        )}
      </td>
    );
  };

  const renderRow = (
    code: string,
    label: string,
    rowKey: string,
    row: Table4RowData,
    drilldownId?: string,
    options?: { isTotal?: boolean; isReversal?: boolean }
  ) => {
    const isTotal = options?.isTotal;
    const isReversal = options?.isReversal;
    const totalTax =
      row.total_tax !== undefined && row.total_tax !== null
        ? row.total_tax
        : (row.igst || 0) + (row.cgst || 0) + (row.sgst || 0) + (row.cess || 0);

    return (
      <tr
        key={code}
        className={`border-b border-[#E5E7EB] transition ${
          isTotal
            ? "bg-[#F8FAFC] font-semibold text-gray-900 border-t-2 border-t-gray-300"
            : isReversal
            ? "hover:bg-red-50/40"
            : "hover:bg-gray-50/60"
        }`}
      >
        <td className="px-4 py-2.5 whitespace-nowrap font-mono text-[12px] font-bold text-gray-800">
          {code}
        </td>
        <td className="px-4 py-2.5 text-[13px] text-gray-800 max-w-[340px]">
          <div className="flex items-center gap-2">
            <span className={isTotal ? "font-bold text-gray-900" : ""}>{label}</span>
          </div>
        </td>
        <td className="px-3 py-2.5 text-center text-[12px] text-gray-500 whitespace-nowrap">
          {row.count ? (
            <span className="rounded bg-gray-100 px-2 py-0.5 font-medium text-gray-700">
              {row.count}
            </span>
          ) : (
            "—"
          )}
        </td>
        {renderCell(row.igst, rowKey, "igst")}
        {renderCell(row.cgst, rowKey, "cgst")}
        {renderCell(row.sgst, rowKey, "sgst")}
        {renderCell(row.cess, rowKey, "cess")}
        <td className="px-4 py-2.5 text-right font-mono text-[13px] font-bold tabular-nums text-gray-900 bg-gray-50/50">
          {formatINR(totalTax)}
        </td>
        <td className="px-4 py-2.5 text-right whitespace-nowrap">
          <div className="inline-flex items-center gap-1.5 justify-end">
            {drilldownId === "4B2" && (
              <button
                onClick={() => setActiveTab("reversals")}
                className="inline-flex items-center gap-1 rounded border border-blue-200 bg-blue-50 px-2 py-1 text-[11px] font-semibold text-blue-800 hover:bg-blue-100 transition"
              >
                Reversal Ledger →
              </button>
            )}
            {drilldownId === "4D1" && (
              <button
                onClick={() => setActiveTab("reversals")}
                className="inline-flex items-center gap-1 rounded border border-indigo-200 bg-indigo-50 px-2 py-1 text-[11px] font-semibold text-indigo-800 hover:bg-indigo-100 transition"
              >
                Reclaim History →
              </button>
            )}
            {drilldownId && (
              <button
                onClick={() => openDrilldown(drilldownId, `${code} — ${label}`)}
                className="inline-flex items-center gap-1 rounded border border-[#E5E7EB] bg-white px-2 py-1 text-[11px] font-semibold text-gray-700 hover:bg-gray-50 hover:border-black transition"
              >
                <svg className="w-3.5 h-3.5 text-gray-400" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M15 12a3 3 0 11-6 0 3 3 0 016 0z" />
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M2.458 12C3.732 7.943 7.523 5 12 5c4.478 0 8.268 2.943 9.542 7-1.274 4.057-5.064 7-9.542 7-4.477 0-8.268-2.943-9.542-7z" />
                </svg>
                Invoices
              </button>
            )}
          </div>
        </td>
      </tr>
    );
  };

  return (
    <div className="space-y-5">
      {/* Action Notification Toast */}
      {actionSuccessMsg && (
        <div className="rounded-xl border border-green-200 bg-green-50 px-4 py-2.5 text-[13px] font-medium text-green-800 flex items-center justify-between">
          <span>{actionSuccessMsg}</span>
          <button onClick={() => setActionSuccessMsg(null)} className="text-green-600 hover:text-green-900">
            ×
          </button>
        </div>
      )}

      {/* Header Banner: Status & Certification */}
      {isFinalized ? (
        <div className="rounded-2xl border border-green-200 bg-gradient-to-r from-green-50/80 to-emerald-50/50 p-5 shadow-sm">
          <div className="flex flex-wrap items-start justify-between gap-4">
            <div>
              <div className="flex items-center gap-2">
                <span className="inline-flex items-center gap-1.5 rounded-full bg-green-100 px-3 py-0.5 text-[11px] font-bold text-green-800 ring-1 ring-green-300 uppercase tracking-wider">
                  <span className="h-2 w-2 rounded-full bg-green-600 animate-pulse" />
                  Finalized & Locked
                </span>
                <h2 className="text-[17px] font-bold text-gray-900">
                  {data.workpaper_title}
                </h2>
              </div>
              <p className="mt-1.5 text-[12px] text-gray-600 leading-relaxed">
                Finalized on{" "}
                <span className="font-semibold text-gray-900">
                  {data.finalized_at ? new Date(data.finalized_at).toLocaleString("en-IN") : "—"}
                </span>{" "}
                by user <span className="font-mono text-gray-700">{data.finalized_by || "Administrator"}</span>.
                Audit Hash: <span className="font-mono text-[11px] bg-white px-1.5 py-0.5 rounded border border-green-200 text-gray-800">{data.audit_hash}</span>
              </p>
              <p className="mt-1 text-[11.5px] italic text-gray-500">
                {data.disclaimer}
              </p>
            </div>
            <div className="flex flex-wrap gap-2">
              <a
                href={gstr3bApi.exportTable4WorkpaperUrl(runId)}
                className="inline-flex items-center gap-1.5 rounded-lg bg-black px-4 py-2 text-[12.5px] font-semibold text-white hover:bg-gray-800 shadow-sm transition"
              >
                <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M4 16v1a3 3 0 003 3h10a3 3 0 003-3v-1m-4-4l-4 4m0 0l-4-4m4 4V4" />
                </svg>
                Export Workpaper (.xlsx)
              </a>
              <button
                onClick={copyAllValues}
                className="inline-flex items-center gap-1.5 rounded-lg border border-[#E5E7EB] bg-white px-3.5 py-2 text-[12.5px] font-semibold text-gray-800 hover:bg-gray-50 shadow-sm transition"
              >
                Copy All Values
              </button>
              <button
                onClick={copyJson}
                className="inline-flex items-center gap-1.5 rounded-lg border border-[#E5E7EB] bg-white px-3.5 py-2 text-[12.5px] font-semibold text-gray-800 hover:bg-gray-50 shadow-sm transition"
              >
                Copy JSON
              </button>
            </div>
          </div>
        </div>
      ) : (
        <div className="rounded-2xl border border-amber-200 bg-gradient-to-r from-amber-50/80 to-yellow-50/50 p-5 shadow-sm">
          <div className="flex flex-wrap items-start justify-between gap-4">
            <div>
              <div className="flex items-center gap-2">
                <span className="inline-flex items-center gap-1.5 rounded-full bg-amber-100 px-3 py-0.5 text-[11px] font-bold text-amber-900 ring-1 ring-amber-300 uppercase tracking-wider">
                  Provisional Draft
                </span>
                <h2 className="text-[17px] font-bold text-gray-900">
                  Provisional GSTR-3B Table 4 Workpaper
                </h2>
              </div>
              <p className="mt-1.5 text-[12.5px] text-gray-700 leading-relaxed">
                {gate.can_finalize ? (
                  <span className="text-emerald-800 font-semibold">
                    ✓ All ITC-affecting exceptions are resolved. Ready to finalize and freeze workpaper.
                  </span>
                ) : (
                  <span className="text-amber-900">
                    <span className="font-semibold">{gate.unresolved_blocking_exceptions}</span> exception(s) require explicit CA disposition before finalization.
                  </span>
                )}
              </p>
              {gate.blocking_summary.length > 0 && (
                <ul className="mt-1.5 list-disc list-inside text-[12px] text-amber-900 space-y-0.5">
                  {gate.blocking_summary.map((s, idx) => (
                    <li key={idx}>{s}</li>
                  ))}
                </ul>
              )}
            </div>
            <div className="flex flex-wrap items-center gap-2">
              {gate.can_finalize ? (
                <button
                  type="button"
                  onClick={() => {
                    setFinalizeError(null);
                    setIsFinalizeModalOpen(true);
                  }}
                  className="inline-flex items-center gap-1.5 rounded-lg bg-black px-4 py-2 text-[12.5px] font-semibold text-white hover:bg-gray-800 shadow-sm transition"
                >
                  <svg className="w-3.5 h-3.5 text-emerald-400" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 15v2m-6 4h12a2 2 0 002-2v-6a2 2 0 00-2-2H6a2 2 0 00-2 2v6a2 2 0 002 2zm10-10V7a4 4 0 00-8 0v4h8z" />
                  </svg>
                  Finalize & Freeze
                </button>
              ) : (
                <button
                  type="button"
                  disabled
                  title={`Cannot finalize: ${gate.unresolved_blocking_exceptions} blocking exception(s) require explicit CA disposition.`}
                  className="inline-flex items-center gap-1.5 rounded-lg bg-gray-200 px-3.5 py-2 text-[12.5px] font-semibold text-gray-400 cursor-not-allowed shadow-none"
                >
                  <svg className="w-3.5 h-3.5 text-gray-400" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 15v2m-6 4h12a2 2 0 002-2v-6a2 2 0 00-2-2H6a2 2 0 00-2 2v6a2 2 0 002 2zm10-10V7a4 4 0 00-8 0v4h8z" />
                  </svg>
                  Finalize & Freeze ({gate.unresolved_blocking_exceptions} blocking)
                </button>
              )}
              {!gate.can_finalize && (
                <button
                  type="button"
                  onClick={() => {
                    setDispositionTargetRecord(null);
                    setIsDispositionModalOpen(true);
                  }}
                  className="inline-flex items-center gap-1.5 rounded-lg bg-amber-700 px-3.5 py-2 text-[12.5px] font-semibold text-white hover:bg-amber-800 shadow-sm transition"
                >
                  Resolve Exceptions ({gate.unresolved_blocking_exceptions})
                </button>
              )}
              <button
                type="button"
                onClick={() => setIsAdjustmentModalOpen(true)}
                className="inline-flex items-center gap-1.5 rounded-lg border border-[#E5E7EB] bg-white px-3.5 py-2 text-[12.5px] font-semibold text-gray-800 hover:bg-gray-50 shadow-sm transition"
              >
                + Add External Adjustment
              </button>
              <a
                href={gstr3bApi.exportTable4WorkpaperUrl(runId)}
                className="inline-flex items-center gap-1.5 rounded-lg border border-[#E5E7EB] bg-white px-3.5 py-2 text-[12.5px] font-semibold text-gray-800 hover:bg-gray-50 shadow-sm transition"
              >
                Export (.xlsx)
              </a>
              <button
                type="button"
                onClick={copyAllValues}
                className="inline-flex items-center gap-1.5 rounded-lg border border-[#E5E7EB] bg-white px-3.5 py-2 text-[12.5px] font-semibold text-gray-800 hover:bg-gray-50 shadow-sm transition"
              >
                Copy Values
              </button>
            </div>
          </div>
        </div>
      )}

      {/* View Mode Selector Tabs */}
      <div className="flex border-b border-[#E5E7EB] gap-6 text-[13px] font-semibold">
        <button
          onClick={() => setActiveTab("workpaper")}
          className={`pb-2.5 border-b-2 transition ${
            activeTab === "workpaper"
              ? "border-black text-gray-900"
              : "border-transparent text-gray-500 hover:text-gray-800"
          }`}
        >
          Form GSTR-3B Table 4 Statutory Workpaper
        </button>
        <button
          onClick={() => setActiveTab("reversals")}
          className={`pb-2.5 border-b-2 transition flex items-center gap-1.5 ${
            activeTab === "reversals"
              ? "border-black text-gray-900"
              : "border-transparent text-gray-500 hover:text-gray-800"
          }`}
        >
          <span>Table 4(B)(2) Reversal & Reclaim Ledger</span>
          <span className="rounded-full bg-blue-100 px-2 py-0.5 text-[10.5px] font-bold text-blue-800">
            Multi-Period
          </span>
        </button>
      </div>

      {activeTab === "reversals" ? (
        <ReversalReclaimLedgerView
          mode="run"
          runId={runId}
          clientId={data.client_gstin}
          authToken={authToken}
          onReclaimSuccess={() => mutate()}
          availableTargetRuns={[
            {
              id: runId,
              period: data.tax_period,
              is_locked: isFinalized,
              status: data.status,
            },
          ]}
        />
      ) : (
        /* Primary Table 4 Statutory Form Grid */
        <div className="rounded-2xl border border-[#E5E7EB] bg-white overflow-hidden shadow-sm">
          <div className="border-b border-[#E5E7EB] px-6 py-3.5 bg-[#FAFAFA] flex items-center justify-between">
            <div>
              <h3 className="text-[14px] font-bold text-gray-900">
                Form GSTR-3B — Table 4 Eligible & Ineligible Input Tax Credit
              </h3>
              <p className="text-[11.5px] text-gray-500">
                Statutory format per CBIC Circular No. 170/02/2022-GST. Click any amount to view itemized ledger.
              </p>
            </div>
            <span className="text-[11px] font-medium text-gray-400">
              Amounts in Indian Rupees (₹)
            </span>
          </div>

          <div className="overflow-x-auto">
            <table className="w-full text-left border-collapse text-[13px]">
              <thead className="bg-[#F8FAFC] text-[11px] font-bold text-gray-500 uppercase tracking-wider border-b border-[#E5E7EB]">
                <tr>
                  <th className="px-4 py-3">Row</th>
                  <th className="px-4 py-3">Statutory Description</th>
                  <th className="px-3 py-3 text-center">Items</th>
                  <th className="px-4 py-3 text-right">Integrated Tax (IGST)</th>
                  <th className="px-4 py-3 text-right">Central Tax (CGST)</th>
                  <th className="px-4 py-3 text-right">State/UT Tax (SGST)</th>
                  <th className="px-4 py-3 text-right">Cess</th>
                  <th className="px-4 py-3 text-right">Total Tax</th>
                  <th className="px-4 py-3 text-right">Action</th>
                </tr>
              </thead>
              <tbody>
                {/* Section 4(A) Header */}
                <tr className="bg-gray-100/70 border-b border-[#E5E7EB]">
                  <td colSpan={9} className="px-4 py-2 font-bold text-[12px] text-gray-800 uppercase tracking-wider">
                    (A) ITC Available (whether in full or part)
                  </td>
                </tr>
                {renderRow("4(A)(1)", "Import of goods (ICEGATE Bill of Entry)", "4a1", t4.section_4a.row_4a1_import_goods, "4A1")}
                {renderRow("4(A)(2)", "Import of services (PR / Self-invoiced RCM)", "4a2", t4.section_4a.row_4a2_import_services, "4A2")}
                {renderRow("4(A)(3)", "Inward supplies liable to reverse charge (other than 1 & 2)", "4a3", t4.section_4a.row_4a3_inward_rcm, "4A3")}
                {renderRow("4(A)(4)", "Inward supplies from Input Service Distributor (ISD)", "4a4", t4.section_4a.row_4a4_isd, "4A4")}
                {renderRow("4(A)(5)", "All other ITC (Domestic B2B supplies from PR ∩ GSTR-2B)", "4a5", t4.section_4a.row_4a5_all_other_itc, "4A5")}
                {renderRow("4(A)", "(A) Total ITC Available [Sum of 4A1 to 4A5]", "4a_tot", t4.section_4a.total_4a, undefined, { isTotal: true })}

                {/* Section 4(B) Header */}
                <tr className="bg-gray-100/70 border-b border-[#E5E7EB]">
                  <td colSpan={9} className="px-4 py-2 font-bold text-[12px] text-gray-800 uppercase tracking-wider">
                    (B) ITC Reversed
                  </td>
                </tr>
                {renderRow("4(B)(1)", "As per rules 38, 42 and 43 & Section 17(5) Blocked Credits", "4b1", t4.section_4b.row_4b1_rule38_42_43_sec175, "4B1", { isReversal: true })}
                {renderRow("4(B)(2)", "Others (Rule 37 180-days payment failure, Rule 37A supplier non-filer)", "4b2", t4.section_4b.row_4b2_others_rule37_37a, "4B2", { isReversal: true })}
                {renderRow("4(B)", "(B) Total ITC Reversed [4B1 + 4B2]", "4b_tot", t4.section_4b.total_4b, undefined, { isTotal: true, isReversal: true })}

                {/* Section 4(C) Net Row */}
                <tr className="bg-emerald-50/60 border-b-2 border-emerald-300 font-bold">
                  <td className="px-4 py-3 font-mono text-[13px] text-emerald-900">4(C)</td>
                  <td className="px-4 py-3 text-[13.5px] text-emerald-950">
                    (C) Net ITC Available [4(A) minus 4(B)]
                  </td>
                  <td className="px-3 py-3 text-center text-emerald-800 text-[12px]">—</td>
                  <td className="px-4 py-3 text-right font-mono text-[13px] tabular-nums text-emerald-950">
                    {formatINR(t4.section_4c_net_itc.igst)}
                  </td>
                  <td className="px-4 py-3 text-right font-mono text-[13px] tabular-nums text-emerald-950">
                    {formatINR(t4.section_4c_net_itc.cgst)}
                  </td>
                  <td className="px-4 py-3 text-right font-mono text-[13px] tabular-nums text-emerald-950">
                    {formatINR(t4.section_4c_net_itc.sgst)}
                  </td>
                  <td className="px-4 py-3 text-right font-mono text-[13px] tabular-nums text-emerald-950">
                    {formatINR(t4.section_4c_net_itc.cess)}
                  </td>
                  <td className="px-4 py-3 text-right font-mono text-[14px] font-black tabular-nums text-emerald-950 bg-emerald-100/50">
                    {formatINR(t4.section_4c_net_itc.total_tax || 0)}
                  </td>
                  <td className="px-4 py-3 text-right text-[11px] font-semibold text-emerald-800">
                    Net Portal Claim
                  </td>
                </tr>

                {/* Section 4(D) Header */}
                <tr className="bg-gray-100/70 border-b border-[#E5E7EB]">
                  <td colSpan={9} className="px-4 py-2 font-bold text-[12px] text-gray-800 uppercase tracking-wider">
                    (D) Other Details (Informational disclosures)
                  </td>
                </tr>
                {renderRow("4(D)(1)", "ITC reclaimed which was reversed under Table 4(B)(2) in earlier tax period", "4d1", t4.section_4d.row_4d1_reclaimed, "4D1")}
                {renderRow("4(D)(2)", "Ineligible ITC under section 16(4) and restricted by Place of Supply", "4d2", t4.section_4d.row_4d2_ineligible_16_4_pos, "4D2")}
              </tbody>
            </table>
          </div>
        </div>
      )}

      {/* Drilldown Slide-Over Drawer */}
      <Table4DrilldownDrawer
        runId={runId}
        authToken={authToken}
        rowId={activeDrilldownRow}
        rowLabel={activeDrilldownLabel}
        isFinalized={isFinalized}
        blockingRecords={(gate as any)?.blocking_records || []}
        onOpenDisposition={handleOpenDispositionForRecord}
        onClose={() => setActiveDrilldownRow(null)}
      />

      {/* Finalize Confirmation Modal */}
      {isFinalizeModalOpen && !isFinalized && (
        <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/50 backdrop-blur-xs">
          <div className="w-full max-w-lg rounded-2xl bg-white p-6 shadow-2xl border border-gray-100 animate-in fade-in zoom-in-95 duration-150">
            <div className="flex items-start gap-3.5">
              <div className="flex h-10 w-10 shrink-0 items-center justify-center rounded-xl bg-gray-900 text-white shadow-sm">
                <svg className="h-5 w-5 text-emerald-400" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 15v2m-6 4h12a2 2 0 002-2v-6a2 2 0 00-2-2H6a2 2 0 00-2 2v6a2 2 0 002 2zm10-10V7a4 4 0 00-8 0v4h8z" />
                </svg>
              </div>
              <div className="flex-1">
                <h3 className="text-[17px] font-bold text-gray-900">
                  Finalize & Freeze Table 4 Workpaper
                </h3>
                <p className="mt-1 text-[12.5px] text-gray-500">
                  Client: <span className="font-mono font-medium text-gray-800">{data.client_gstin}</span> • Period: <span className="font-semibold text-gray-800">{data.tax_period}</span>
                </p>
              </div>
              <button
                type="button"
                onClick={() => !isFinalizing && setIsFinalizeModalOpen(false)}
                disabled={isFinalizing}
                className="text-gray-400 hover:text-gray-600 disabled:opacity-50"
              >
                ✕
              </button>
            </div>

            {/* Key Statutory Summary Numbers */}
            <div className="mt-5 grid grid-cols-3 gap-3 rounded-xl bg-gray-50 p-3.5 border border-gray-100 text-center">
              <div>
                <p className="text-[10.5px] font-semibold text-gray-400 uppercase tracking-wider">Net ITC (4C)</p>
                <p className="mt-1 font-mono text-[13.5px] font-bold text-gray-900 tabular-nums">
                  {formatINR(t4.section_4c_net_itc.total_tax ?? ((t4.section_4c_net_itc.igst || 0) + (t4.section_4c_net_itc.cgst || 0) + (t4.section_4c_net_itc.sgst || 0) + (t4.section_4c_net_itc.cess || 0)))}
                </p>
              </div>
              <div>
                <p className="text-[10.5px] font-semibold text-gray-400 uppercase tracking-wider">Reversals (4B)</p>
                <p className="mt-1 font-mono text-[13.5px] font-bold text-amber-700 tabular-nums">
                  {formatINR(t4.section_4b.total_4b.total_tax ?? ((t4.section_4b.total_4b.igst || 0) + (t4.section_4b.total_4b.cgst || 0) + (t4.section_4b.total_4b.sgst || 0) + (t4.section_4b.total_4b.cess || 0)))}
                </p>
              </div>
              <div>
                <p className="text-[10.5px] font-semibold text-gray-400 uppercase tracking-wider">Reclaimed (4D1)</p>
                <p className="mt-1 font-mono text-[13.5px] font-bold text-emerald-700 tabular-nums">
                  {formatINR(t4.section_4d.row_4d1_reclaimed.total_tax ?? ((t4.section_4d.row_4d1_reclaimed.igst || 0) + (t4.section_4d.row_4d1_reclaimed.cgst || 0) + (t4.section_4d.row_4d1_reclaimed.sgst || 0) + (t4.section_4d.row_4d1_reclaimed.cess || 0)))}
                </p>
              </div>
            </div>

            {/* Statutory Notice / Warning Box */}
            <div className="mt-4 rounded-xl border border-amber-200 bg-amber-50/70 p-3.5 text-[12px] text-amber-900 leading-relaxed">
              <div className="flex gap-2">
                <span className="font-bold text-amber-950 shrink-0">Statutory Notice:</span>
                <span>
                  Finalizing will permanently seal this Table 4 workpaper, compute an immutable SHA-256 audit hash, and lock the reconciliation run. All further external adjustments and exception dispositions will be locked.
                </span>
              </div>
            </div>

            {/* Finalize Error Message */}
            {finalizeError && (
              <div className="mt-3 rounded-lg border border-red-200 bg-red-50 p-3 text-[12px] text-red-700">
                {finalizeError}
              </div>
            )}

            {/* Modal Actions */}
            <div className="mt-6 flex justify-end gap-3">
              <button
                type="button"
                onClick={() => setIsFinalizeModalOpen(false)}
                disabled={isFinalizing}
                className="rounded-lg border border-gray-200 bg-white px-4 py-2 text-[13px] font-semibold text-gray-700 hover:bg-gray-50 transition disabled:opacity-50 cursor-pointer"
              >
                Cancel
              </button>
              <button
                type="button"
                onClick={handleFinalize}
                disabled={isFinalizing}
                className="inline-flex items-center gap-2 rounded-lg bg-black px-4 py-2 text-[13px] font-semibold text-white hover:bg-gray-800 transition disabled:opacity-50 shadow-sm cursor-pointer"
              >
                {isFinalizing ? (
                  <>
                    <svg className="h-4 w-4 animate-spin text-white" fill="none" viewBox="0 0 24 24">
                      <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
                      <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8v8z" />
                    </svg>
                    <span>Finalizing & Locking…</span>
                  </>
                ) : (
                  <>
                    <svg className="w-4 h-4 text-emerald-400" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                      <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M5 13l4 4L19 7" />
                    </svg>
                    <span>Confirm & Lock Workpaper</span>
                  </>
                )}
              </button>
            </div>
          </div>
        </div>
      )}

      {/* External Adjustment Modal */}
      <Table4AdjustmentModal
        runId={runId}
        authToken={authToken}
        isOpen={!isFinalized && isAdjustmentModalOpen}
        onClose={() => setIsAdjustmentModalOpen(false)}
        onSuccess={() => {
          void mutate();
          void revalidateReconciliationRun(runId, { table4: true, drilldown: true });
        }}
      />

      {/* Exception Disposition Modal */}
      <Table4DispositionModal
        runId={runId}
        authToken={authToken}
        isOpen={!isFinalized && isDispositionModalOpen}
        onClose={() => {
          setIsDispositionModalOpen(false);
          setDispositionTargetRecord(null);
        }}
        onSuccess={() => {
          void mutate();
          void revalidateReconciliationRun(runId);
          setIsDispositionModalOpen(false);
          setDispositionTargetRecord(null);
        }}
        blockingRecords={gate.blocking_summary.length > 0 ? (gate as any).blocking_records || [] : []}
        targetRecord={dispositionTargetRecord}
      />
    </div>
  );
}
