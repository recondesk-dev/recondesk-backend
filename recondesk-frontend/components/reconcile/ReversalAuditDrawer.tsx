"use client";

import type { ReversalLedgerEntryDto } from "@/lib/api";
import { formatINR } from "@/lib/format";
import {
  REVERSAL_STATUS_META,
  STATUTORY_REASON_LABELS,
  paiseToRupees,
} from "./reversalLedgerLogic";

interface ReversalAuditDrawerProps {
  entry: ReversalLedgerEntryDto | null;
  onClose: () => void;
}

export function ReversalAuditDrawer({ entry, onClose }: ReversalAuditDrawerProps) {
  if (!entry) return null;

  const statusMeta = REVERSAL_STATUS_META[entry.status] || {
    label: entry.status,
    badgeBg: "bg-gray-100",
    badgeText: "text-gray-800",
    badgeBorder: "border-gray-300",
    dotColor: "bg-gray-500",
  };

  const evidence = entry.condition_evidence || {};
  const totalRevPaise =
    entry.reversed_total_tax_paise ??
    ((entry.reversed_igst_paise || 0) +
      (entry.reversed_cgst_paise || 0) +
      (entry.reversed_sgst_paise || 0) +
      (entry.reversed_cess_paise || 0));

  const cachedRecPaise =
    (entry.cached_reclaimed_igst_paise || 0) +
    (entry.cached_reclaimed_cgst_paise || 0) +
    (entry.cached_reclaimed_sgst_paise || 0) +
    (entry.cached_reclaimed_cess_paise || 0);

  const flatRecPaise =
    (entry.reclaimed_igst_paise || 0) +
    (entry.reclaimed_cgst_paise || 0) +
    (entry.reclaimed_sgst_paise || 0) +
    (entry.reclaimed_cess_paise || 0);

  const totalRecPaise = entry.reclaimed_total_tax_paise ?? (cachedRecPaise || flatRecPaise);

  const reversedTotal = paiseToRupees(totalRevPaise);
  const reclaimedTotal = paiseToRupees(totalRecPaise);
  const outstandingTotal =
    entry.remaining_balances_paise?.total != null
      ? paiseToRupees(entry.remaining_balances_paise.total)
      : Math.max(0, reversedTotal - reclaimedTotal);

  return (
    <div className="fixed inset-0 z-50 overflow-hidden bg-black/40 backdrop-blur-sm transition-opacity">
      <div className="fixed inset-y-0 right-0 flex max-w-full pl-10">
        <div className="w-screen max-w-xl bg-white shadow-2xl flex flex-col">
          {/* Header */}
          <div className="border-b border-[#E5E7EB] px-6 py-4 flex items-center justify-between bg-[#FAFAFA]">
            <div>
              <div className="flex items-center gap-2">
                <span className="rounded bg-black px-2 py-0.5 text-[11px] font-bold text-white uppercase tracking-wider">
                  Audit Provenance
                </span>
                <span
                  className={`inline-flex items-center gap-1.5 rounded-full px-2.5 py-0.5 text-[11px] font-bold border ${statusMeta.badgeBg} ${statusMeta.badgeText} ${statusMeta.badgeBorder}`}
                >
                  <span className={`h-1.5 w-1.5 rounded-full ${statusMeta.dotColor}`} />
                  {statusMeta.label}
                </span>
              </div>
              <h2 className="mt-1.5 text-[16px] font-bold text-gray-900 font-mono">
                {entry.document_number}
              </h2>
              <p className="text-[12px] text-gray-500">
                Statutory lifecycle tracking & legal evidentiary history
              </p>
            </div>
            <button
              onClick={onClose}
              className="rounded-lg p-2 text-gray-400 hover:bg-gray-100 hover:text-gray-700 transition"
              title="Close drawer"
            >
              ✕
            </button>
          </div>

          {/* Drawer Body */}
          <div className="flex-1 overflow-y-auto p-6 space-y-5">
            {/* Financial Balance Overview */}
            <div className="rounded-xl border border-[#E5E7EB] bg-[#F8FAFC] p-4">
              <h3 className="text-[11px] font-bold text-gray-500 uppercase tracking-wider mb-2">
                Tax-Head Ledger Balance
              </h3>
              <div className="grid grid-cols-3 gap-3 text-center">
                <div className="rounded-lg bg-white p-2.5 border border-gray-200">
                  <span className="text-[11px] text-gray-500 block">Total Reversed</span>
                  <span className="font-bold text-gray-900 font-mono text-[14px]">
                    {formatINR(reversedTotal)}
                  </span>
                </div>
                <div className="rounded-lg bg-white p-2.5 border border-gray-200">
                  <span className="text-[11px] text-gray-500 block">Total Reclaimed</span>
                  <span className="font-bold text-emerald-700 font-mono text-[14px]">
                    {formatINR(reclaimedTotal)}
                  </span>
                </div>
                <div className="rounded-lg bg-white p-2.5 border border-gray-200">
                  <span className="text-[11px] text-gray-500 block">Outstanding</span>
                  <span className="font-bold text-indigo-700 font-mono text-[14px]">
                    {formatINR(outstandingTotal)}
                  </span>
                </div>
              </div>

              {/* Head Breakdown */}
              <div className="mt-3 border-t border-gray-200 pt-2.5 text-[12px] grid grid-cols-4 gap-2 text-center text-gray-700">
                <div>
                  <span className="text-gray-400 block text-[10.5px]">IGST</span>
                  <span className="font-mono font-medium">₹{paiseToRupees(entry.reversed_igst_paise)}</span>
                </div>
                <div>
                  <span className="text-gray-400 block text-[10.5px]">CGST</span>
                  <span className="font-mono font-medium">₹{paiseToRupees(entry.reversed_cgst_paise)}</span>
                </div>
                <div>
                  <span className="text-gray-400 block text-[10.5px]">SGST</span>
                  <span className="font-mono font-medium">₹{paiseToRupees(entry.reversed_sgst_paise)}</span>
                </div>
                <div>
                  <span className="text-gray-400 block text-[10.5px]">Cess</span>
                  <span className="font-mono font-medium">₹{paiseToRupees(entry.reversed_cess_paise)}</span>
                </div>
              </div>
            </div>

            {/* Document Details */}
            <div className="rounded-xl border border-gray-200 p-4 space-y-2 text-[12.5px]">
              <h3 className="text-[11px] font-bold text-gray-500 uppercase tracking-wider">
                Document & Provenance Origin
              </h3>
              <div className="grid grid-cols-2 gap-2 text-gray-700">
                <div>
                  <span className="text-gray-400 block text-[11px]">Supplier GSTIN</span>
                  <span className="font-mono font-semibold text-gray-900">{entry.supplier_gstin}</span>
                </div>
                <div>
                  <span className="text-gray-400 block text-[11px]">Document Date</span>
                  <span className="font-medium text-gray-900">{entry.document_date || "—"}</span>
                </div>
                <div>
                  <span className="text-gray-400 block text-[11px]">Source Return Period</span>
                  <span className="font-medium text-gray-900">{entry.reversal_tax_period}</span>
                </div>
                <div>
                  <span className="text-gray-400 block text-[11px]">Source Run Identifier</span>
                  <span className="font-mono text-gray-900 text-[11.5px]">{entry.source_run_id?.substring(0, 16)}…</span>
                </div>
              </div>
              <div className="border-t border-gray-100 pt-2 text-[12px]">
                <span className="text-gray-400 block text-[11px]">Statutory Classification</span>
                <span className="font-semibold text-gray-800">
                  {STATUTORY_REASON_LABELS[entry.statutory_reason] || entry.statutory_reason}
                </span>
              </div>
            </div>

            {/* Condition Fulfillment Evidence */}
            <div className="rounded-xl border border-blue-200 bg-blue-50/40 p-4 space-y-2 text-[12.5px]">
              <h3 className="text-[11px] font-bold text-blue-950 uppercase tracking-wider flex items-center gap-1.5">
                <span className="h-1.5 w-1.5 rounded-full bg-blue-600" />
                Condition Fulfillment Evidence
              </h3>
              {entry.condition_fulfilled_at ? (
                <div className="space-y-2 text-gray-700">
                  <div className="grid grid-cols-2 gap-2">
                    <div>
                      <span className="text-gray-400 block text-[11px]">Fulfilled At</span>
                      <span className="font-medium text-gray-900">
                        {new Date(entry.condition_fulfilled_at).toLocaleString("en-IN")}
                      </span>
                    </div>
                    {evidence.payment_date && (
                      <div>
                        <span className="text-gray-400 block text-[11px]">Payment Date</span>
                        <span className="font-medium text-gray-900">{evidence.payment_date}</span>
                      </div>
                    )}
                    {evidence.payment_reference && (
                      <div>
                        <span className="text-gray-400 block text-[11px]">Payment Reference</span>
                        <span className="font-mono font-medium text-gray-900">{evidence.payment_reference}</span>
                      </div>
                    )}
                    {evidence.supplier_filing_arn && (
                      <div>
                        <span className="text-gray-400 block text-[11px]">Supplier GSTR-3B ARN</span>
                        <span className="font-mono font-medium text-gray-900">{evidence.supplier_filing_arn}</span>
                      </div>
                    )}
                    {evidence.receipt_evidence_ref && (
                      <div>
                        <span className="text-gray-400 block text-[11px]">Receipt / GRN Ref</span>
                        <span className="font-mono font-medium text-gray-900">{evidence.receipt_evidence_ref}</span>
                      </div>
                    )}
                  </div>
                  {evidence.notes && (
                    <div className="border-t border-blue-100 pt-1 text-[11.5px] text-gray-600">
                      <span className="font-semibold text-gray-700">Submitter Notes:</span> {evidence.notes}
                    </div>
                  )}
                </div>
              ) : (
                <p className="text-[12px] italic text-gray-500">
                  No fulfillment evidence recorded yet. Reversal condition is pending.
                </p>
              )}
            </div>

            {/* CA Authorization Signoff */}
            <div className="rounded-xl border border-emerald-200 bg-emerald-50/40 p-4 space-y-2 text-[12.5px]">
              <h3 className="text-[11px] font-bold text-emerald-950 uppercase tracking-wider flex items-center gap-1.5">
                <span className="h-1.5 w-1.5 rounded-full bg-emerald-600" />
                Chartered Accountant Authorization
              </h3>
              {entry.reclaim_authorized_at ? (
                <div className="space-y-1.5 text-gray-700">
                  <div className="grid grid-cols-2 gap-2">
                    <div>
                      <span className="text-gray-400 block text-[11px]">Authorized At</span>
                      <span className="font-medium text-gray-900">
                        {new Date(entry.reclaim_authorized_at).toLocaleString("en-IN")}
                      </span>
                    </div>
                    <div>
                      <span className="text-gray-400 block text-[11px]">Authorized By</span>
                      <span className="font-mono text-gray-900">{entry.reclaim_authorized_by || "CA Signoff"}</span>
                    </div>
                  </div>
                  {entry.reclaim_authorization_notes && (
                    <div className="border-t border-emerald-100 pt-1 text-[11.5px] text-gray-600">
                      <span className="font-semibold text-gray-700">Signoff Remarks:</span> {entry.reclaim_authorization_notes}
                    </div>
                  )}
                </div>
              ) : (
                <p className="text-[12px] italic text-gray-500">
                  Reclaim is not yet authorized by a Chartered Accountant.
                </p>
              )}
            </div>

            {/* Cryptographic State Digest */}
            <div className="rounded-xl border border-gray-200 bg-gray-50 p-3 text-[11.5px] font-mono text-gray-600 break-all">
              <span className="text-gray-400 block font-sans text-[10.5px] uppercase tracking-wider mb-1 font-bold">
                Cryptographic State Sealing Digest
              </span>
              {entry.state_digest || "—"}
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}
