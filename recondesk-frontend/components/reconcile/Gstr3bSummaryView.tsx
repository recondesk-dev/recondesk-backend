"use client";

import Link from "next/link";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import useSWR from "swr";

import type {
  Gstr3bReconciliationResult,
  Gstr3bHeadResult,
  Gstr3bDrc01cResult,
  Gstr3bFiledSummary,
  Gstr3bSupplyRow,
  Gstr3bTaxHeads,
} from "@/lib/api";
import { gstr3bApi, isApiError } from "@/lib/api";
import { formatINR } from "@/lib/format";
import { listGstr1Runs } from "@/lib/gstr1Reconcile";
import {
  CompactStatAmount,
  SectionHeader,
  sectionContainerClass,
  StatCard,
  statCardsGridClass,
} from "./ResultsUi";

const ITC_SOURCE_ORDER = ["IMPG", "IMPS", "ISRC", "ISD", "OTH"] as const;
const ITC_SOURCE_LABELS: Record<string, string> = {
  IMPG: "Import of goods",
  IMPS: "Import of services",
  ISRC: "Inward supplies liable to reverse charge",
  ISD: "Input Service Distributor",
  OTH: "All other ITC",
};

function formatPeriod(period: string): string {
  const m = period.match(/^(\d{4})-(\d{2})$/);
  if (!m) return period || "—";
  const d = new Date(Number(m[1]), Number(m[2]) - 1, 1);
  return d.toLocaleString("en-IN", { month: "long", year: "numeric" });
}

function StatusBadge({ status }: { status: string }) {
  if (status === "MATCHED") {
    return (
      <span className="inline-flex items-center gap-1.5 rounded-full bg-green-50 px-3 py-1 text-[12px] font-semibold text-green-700 ring-1 ring-green-200">
        <span className="h-1.5 w-1.5 rounded-full bg-green-500" />
        MATCHED
      </span>
    );
  }
  if (status === "OVERCLAIMED") {
    return (
      <span className="inline-flex items-center gap-1.5 rounded-full bg-red-50 px-3 py-1 text-[12px] font-semibold text-red-700 ring-1 ring-red-200">
        <span className="h-1.5 w-1.5 rounded-full bg-red-500" />
        OVERCLAIMED
      </span>
    );
  }
  if (status === "MIXED") {
    return (
      <span
        className="inline-flex items-center gap-1.5 rounded-full bg-violet-50 px-3 py-1 text-[12px] font-semibold text-violet-800 ring-1 ring-violet-200"
        title="Some tax heads are overclaimed and others underclaimed — see Net difference for the overall position"
      >
        <span className="h-1.5 w-1.5 rounded-full bg-violet-500" />
        MIXED
      </span>
    );
  }
  return (
    <span className="inline-flex items-center gap-1.5 rounded-full bg-amber-50 px-3 py-1 text-[12px] font-semibold text-amber-700 ring-1 ring-amber-200">
      <span className="h-1.5 w-1.5 rounded-full bg-amber-500" />
      UNDERCLAIMED
    </span>
  );
}

function HeadStatusCell({ status }: { status: string }) {
  if (status === "MATCHED")
    return <span className="text-green-600 text-[13px] font-medium">Matched</span>;
  if (status === "OVERCLAIMED")
    return <span className="text-red-600 text-[13px] font-medium">Overclaimed</span>;
  return <span className="text-amber-600 text-[13px] font-medium">Underclaimed</span>;
}

function diffColor(diff: number): string {
  if (diff === 0) return "text-gray-800";
  if (diff > 0) return "text-red-600";
  return "text-amber-600";
}

function DiffAmount({ diff }: { diff: number }) {
  const sign = diff > 0 ? "+" : diff < 0 ? "−" : "";
  return (
    <span className={`tabular-nums font-semibold ${diffColor(diff)}`}>
      {sign}
      {formatINR(Math.abs(diff))}
    </span>
  );
}

function taxHeadsTotal(h: Gstr3bTaxHeads | undefined): number {
  if (!h) return 0;
  return (h.igst || 0) + (h.cgst || 0) + (h.sgst || 0) + (h.cess || 0);
}

function supplyNonzero(s: Gstr3bSupplyRow | undefined): boolean {
  if (!s) return false;
  return (
    (s.taxable_value || 0) !== 0 ||
    (s.igst || 0) !== 0 ||
    (s.cgst || 0) !== 0 ||
    (s.sgst || 0) !== 0 ||
    (s.cess || 0) !== 0
  );
}

function secondaryHasSignal(filed: Gstr3bFiledSummary): boolean {
  if (supplyNonzero(filed.osup_zero)) return true;
  if (supplyNonzero(filed.osup_nil_exmp)) return true;
  if (supplyNonzero(filed.isup_rev)) return true;
  if (supplyNonzero(filed.osup_nongst)) return true;
  if ((filed.inward_sup || []).some((r) => (r.inter || 0) !== 0 || (r.intra || 0) !== 0))
    return true;
  if (taxHeadsTotal(filed.interest_late_fee) !== 0) return true;
  if (taxHeadsTotal(filed.late_fee) !== 0) return true;
  return false;
}

function Drc01cBanner({ drc }: { drc: Gstr3bDrc01cResult }) {
  const pctLabel =
    drc.excess_pct == null
      ? "n/a (2B available is ₹0)"
      : `${drc.excess_pct.toLocaleString("en-IN", { maximumFractionDigits: 2 })}%`;

  if (drc.threshold_status === "CLEAR") {
    return (
      <div className="rounded-xl border border-[#E5E7EB] bg-[#FAFAFA] px-4 py-3">
        <div className="flex flex-wrap items-center justify-between gap-2">
          <p className="text-[13px] font-semibold text-gray-800">DRC-01C — CLEAR</p>
          <span className="rounded-full bg-green-50 px-2.5 py-0.5 text-[11px] font-semibold text-green-700 ring-1 ring-green-200">
            No Rule 88D trigger
          </span>
        </div>
        <p className="mt-1.5 text-[12px] text-gray-500 leading-relaxed">
          No overclaim vs GSTR-2B. Portal intimation requires excess &gt; {drc.pct_threshold}%{" "}
          <span className="font-medium">and</span> &gt; {formatINR(drc.amount_threshold)}.
        </p>
      </div>
    );
  }

  if (drc.triggers_drc01c) {
    return (
      <div className="rounded-xl border border-red-200 bg-red-50 px-4 py-3">
        <div className="flex flex-wrap items-center justify-between gap-2">
          <p className="text-[13px] font-semibold text-red-800">DRC-01C — TRIGGER</p>
          <span className="rounded-full bg-red-100 px-2.5 py-0.5 text-[11px] font-semibold text-red-800 ring-1 ring-red-200">
            Threshold crossed
          </span>
        </div>
        <p className="mt-1.5 text-[12px] text-red-700/90 leading-relaxed">
          Excess {formatINR(drc.excess_amount)} ({pctLabel} of 2B). Both Rule 88D gates exceeded
          (&gt; {drc.pct_threshold}% and &gt; {formatINR(drc.amount_threshold)}). Portal may issue
          Form GST DRC-01C Part A.
        </p>
      </div>
    );
  }

  return (
    <div className="rounded-xl border border-amber-200 bg-amber-50 px-4 py-3">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <p className="text-[13px] font-semibold text-amber-900">DRC-01C — BELOW THRESHOLD</p>
        <span className="rounded-full bg-amber-100 px-2.5 py-0.5 text-[11px] font-semibold text-amber-900 ring-1 ring-amber-200">
          Overclaim, under trigger
        </span>
      </div>
      <p className="mt-1.5 text-[12px] text-amber-800/90 leading-relaxed">
        Overclaim {formatINR(drc.excess_amount)} ({pctLabel}) is below the dual gate (&gt;{" "}
        {drc.pct_threshold}% <span className="font-medium">and</span> &gt;{" "}
        {formatINR(drc.amount_threshold)}). Review before filing; portal intimation is unlikely.
      </p>
    </div>
  );
}

function ComparisonTable({ result }: { result: Gstr3bReconciliationResult }) {
  const rows: { label: string; head: Gstr3bHeadResult }[] = [
    { label: "IGST", head: result.igst },
    { label: "CGST", head: result.cgst },
    { label: "SGST", head: result.sgst },
    { label: "Total", head: result.total },
  ];
  return (
    <div className="overflow-x-auto rounded-xl border border-[#E5E7EB]">
      <table className="w-full table-fixed border-collapse text-left text-[13px]">
        <thead className="bg-[#FAFAFA] text-[11px] font-semibold uppercase tracking-wider text-gray-400">
          <tr>
            <th className="px-4 py-3">Tax Head</th>
            <th className="px-4 py-3 text-right">GSTR-2B Available</th>
            <th className="px-4 py-3 text-right">GSTR-3B Claimed</th>
            <th className="px-4 py-3 text-right">Difference</th>
            <th className="px-4 py-3">Status</th>
          </tr>
        </thead>
        <tbody>
          {rows.map(({ label, head }, i) => (
            <tr
              key={label}
              className={`border-t border-[#F5F5F5] ${
                i === rows.length - 1 ? "bg-[#FAFAFA] font-semibold" : "bg-white"
              }`}
            >
              <td className="px-4 py-3 text-gray-700">{label}</td>
              <td className="px-4 py-3 text-right tabular-nums">{formatINR(head.gstr2b)}</td>
              <td className="px-4 py-3 text-right tabular-nums">{formatINR(head.gstr3b)}</td>
              <td className="px-4 py-3 text-right">
                <DiffAmount diff={head.difference} />
              </td>
              <td className="px-4 py-3">
                <HeadStatusCell status={head.status} />
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function ItcBySourceTable({ filed }: { filed: Gstr3bFiledSummary }) {
  return (
    <div className="overflow-x-auto rounded-xl border border-[#E5E7EB]">
      <table className="w-full border-collapse text-left text-[13px]">
        <thead className="bg-[#FAFAFA] text-[11px] font-semibold uppercase tracking-wider text-gray-400">
          <tr>
            <th className="px-4 py-3">Source</th>
            <th className="px-4 py-3 text-right">IGST</th>
            <th className="px-4 py-3 text-right">CGST</th>
            <th className="px-4 py-3 text-right">SGST</th>
            <th className="px-4 py-3 text-right">Cess</th>
            <th className="px-4 py-3 text-right">Total</th>
          </tr>
        </thead>
        <tbody>
          {ITC_SOURCE_ORDER.map((ty) => {
            const h = filed.itc_avl_by_source?.[ty] || {
              igst: 0,
              cgst: 0,
              sgst: 0,
              cess: 0,
            };
            const tot = taxHeadsTotal(h);
            const muted = tot === 0;
            return (
              <tr
                key={ty}
                className={`border-t border-[#F5F5F5] ${muted ? "text-gray-400" : "text-gray-800"}`}
              >
                <td className="px-4 py-3">
                  <span className="font-medium">{ty}</span>
                  <span className="ml-2 text-[11px] text-gray-400">
                    {ITC_SOURCE_LABELS[ty] || ty}
                  </span>
                </td>
                <td className="px-4 py-3 text-right tabular-nums">{formatINR(h.igst)}</td>
                <td className="px-4 py-3 text-right tabular-nums">{formatINR(h.cgst)}</td>
                <td className="px-4 py-3 text-right tabular-nums">{formatINR(h.sgst)}</td>
                <td className="px-4 py-3 text-right tabular-nums">{formatINR(h.cess)}</td>
                <td className="px-4 py-3 text-right tabular-nums font-medium">
                  {formatINR(tot)}
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}

function SupplyRowTable({
  label,
  row,
  emphasize,
}: {
  label: string;
  row: Gstr3bSupplyRow;
  emphasize?: boolean;
}) {
  const nz = supplyNonzero(row);
  return (
    <div
      className={`rounded-xl border px-4 py-3 ${
        emphasize
          ? "border-[#E5E7EB] bg-white"
          : nz
            ? "border-[#E5E7EB] bg-white"
            : "border-[#F0F0F0] bg-[#FAFAFA] text-gray-400"
      }`}
    >
      <p
        className={`text-[12px] font-semibold ${
          emphasize || nz ? "text-gray-800" : "text-gray-400"
        }`}
      >
        {label}
        {!nz && !emphasize ? (
          <span className="ml-2 text-[11px] font-normal">— nil</span>
        ) : null}
      </p>
      <div className="mt-2 grid grid-cols-2 gap-x-4 gap-y-1 text-[12px] sm:grid-cols-5">
        <div>
          <span className="text-gray-400">Taxable</span>
          <p className="tabular-nums font-medium">{formatINR(row.taxable_value)}</p>
        </div>
        <div>
          <span className="text-gray-400">IGST</span>
          <p className="tabular-nums font-medium">{formatINR(row.igst)}</p>
        </div>
        <div>
          <span className="text-gray-400">CGST</span>
          <p className="tabular-nums font-medium">{formatINR(row.cgst)}</p>
        </div>
        <div>
          <span className="text-gray-400">SGST</span>
          <p className="tabular-nums font-medium">{formatINR(row.sgst)}</p>
        </div>
        <div>
          <span className="text-gray-400">Cess</span>
          <p className="tabular-nums font-medium">{formatINR(row.cess)}</p>
        </div>
      </div>
    </div>
  );
}

function SecondaryFiledAccordion({ filed }: { filed: Gstr3bFiledSummary }) {
  const hasSignal = secondaryHasSignal(filed);
  const [open, setOpen] = useState(hasSignal);

  useEffect(() => {
    if (hasSignal) setOpen(true);
  }, [hasSignal]);

  return (
    <div className="rounded-xl border border-[#E5E7EB] bg-[#FAFAFA]">
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        className="flex w-full items-center justify-between px-4 py-3 text-left"
      >
        <div>
          <p className="text-[13px] font-semibold text-gray-600">
            Other filed tables (3.1b–e, Table 5, interest / late fee)
          </p>
          <p className="mt-0.5 text-[11px] text-gray-400">
            {hasSignal
              ? "Nonzero values present — expanded for review"
              : "All zero in this filing — expand to verify"}
          </p>
        </div>
        <span className="text-[12px] font-medium text-gray-500">{open ? "Hide" : "Show"}</span>
      </button>
      {open && (
        <div className="space-y-3 border-t border-[#E5E7EB] px-4 py-4">
          <SupplyRowTable label="3.1(b) Zero-rated outward" row={filed.osup_zero} />
          <SupplyRowTable label="3.1(c) Nil / exempt outward" row={filed.osup_nil_exmp} />
          <SupplyRowTable label="3.1(d) Inward supplies (RCM)" row={filed.isup_rev} />
          <SupplyRowTable label="3.1(e) Non-GST outward" row={filed.osup_nongst} />

          <div
            className={`rounded-xl border px-4 py-3 ${
              (filed.inward_sup || []).some((r) => r.inter || r.intra)
                ? "border-[#E5E7EB] bg-white"
                : "border-[#F0F0F0] bg-[#FAFAFA] text-gray-400"
            }`}
          >
            <p className="text-[12px] font-semibold">Table 5 — Inward exempt / nil / non-GST</p>
            {(filed.inward_sup || []).length === 0 ? (
              <p className="mt-1 text-[12px]">No rows</p>
            ) : (
              <ul className="mt-2 space-y-1 text-[12px]">
                {filed.inward_sup.map((r, i) => (
                  <li key={`${r.ty}-${i}`} className="tabular-nums">
                    {r.ty}: inter {formatINR(r.inter)} · intra {formatINR(r.intra)}
                  </li>
                ))}
              </ul>
            )}
          </div>

          <div
            className={`rounded-xl border px-4 py-3 ${
              taxHeadsTotal(filed.interest_late_fee) !== 0
                ? "border-[#E5E7EB] bg-white"
                : "border-[#F0F0F0] bg-[#FAFAFA] text-gray-400"
            }`}
          >
            <p className="text-[12px] font-semibold">5.1 Interest</p>
            <p className="mt-1 text-[12px] tabular-nums">
              IGST {formatINR(filed.interest_late_fee.igst)} · CGST{" "}
              {formatINR(filed.interest_late_fee.cgst)} · SGST{" "}
              {formatINR(filed.interest_late_fee.sgst)}
            </p>
          </div>

          <div
            className={`rounded-xl border px-4 py-3 ${
              taxHeadsTotal(filed.late_fee) !== 0
                ? "border-[#E5E7EB] bg-white"
                : "border-[#F0F0F0] bg-[#FAFAFA] text-gray-400"
            }`}
          >
            <p className="text-[12px] font-semibold">5.1 Late fee</p>
            <p className="mt-1 text-[12px] tabular-nums">
              CGST {formatINR(filed.late_fee.cgst)} · SGST {formatINR(filed.late_fee.sgst)}
            </p>
          </div>
        </div>
      )}
    </div>
  );
}

function UploadArea({
  onFile,
  loading,
  error,
}: {
  onFile: (f: File) => void;
  loading: boolean;
  error: string | null;
}) {
  const inputRef = useRef<HTMLInputElement>(null);
  const [dragging, setDragging] = useState(false);

  const handleFiles = (files: FileList | null) => {
    const f = files?.[0];
    if (!f) return;
    if (!f.name.toLowerCase().endsWith(".json")) {
      alert("Please upload a .json file downloaded from the GST portal.");
      return;
    }
    onFile(f);
  };

  return (
    <div className="flex flex-col items-center justify-center py-16">
      <div
        onDragOver={(e) => {
          e.preventDefault();
          setDragging(true);
        }}
        onDragLeave={() => setDragging(false)}
        onDrop={(e) => {
          e.preventDefault();
          setDragging(false);
          handleFiles(e.dataTransfer.files);
        }}
        className={`flex w-full max-w-lg flex-col items-center justify-center gap-4 rounded-2xl border-2 border-dashed px-8 py-12 text-center transition-colors ${
          dragging ? "border-brand bg-brand/5" : "border-[#E5E7EB] bg-[#FAFAFA]"
        }`}
      >
        <div>
          <p className="text-[14px] font-medium text-gray-800">Upload GSTR-3B JSON</p>
          <p className="mt-1.5 text-[12px] text-gray-400 leading-relaxed">
            GST Portal → Returns → GSTR-3B → View Filed Returns → Download JSON
          </p>
        </div>
        <input
          ref={inputRef}
          type="file"
          accept=".json"
          className="hidden"
          onChange={(e) => handleFiles(e.target.files)}
        />
        <button
          type="button"
          disabled={loading}
          onClick={() => inputRef.current?.click()}
          className="mt-2 inline-flex items-center gap-2 rounded-xl bg-brand px-5 py-2.5 text-[13px] font-medium text-white shadow-sm hover:bg-brand/90 disabled:opacity-50"
        >
          {loading ? "Uploading…" : "Upload GSTR-3B JSON"}
        </button>
        {error && <p className="mt-1 text-[12px] text-red-500">{error}</p>}
      </div>
    </div>
  );
}

function RelatedChecks({
  runId,
  authToken,
  clientGstinId,
  taxPeriod,
  showStandaloneLink,
}: {
  runId: string;
  authToken: string;
  clientGstinId?: string | null;
  taxPeriod: string;
  showStandaloneLink?: boolean;
}) {
  const { data: gstr1Runs } = useSWR(
    authToken && clientGstinId
      ? [`gstr1-runs-for-3b`, clientGstinId, taxPeriod]
      : null,
    () => listGstr1Runs(authToken, { client_gstin_id: clientGstinId!, limit: 20 }),
    { shouldRetryOnError: false }
  );

  const matchingGstr1 = useMemo(() => {
    if (!gstr1Runs?.length || !taxPeriod) return null;
    const norm = taxPeriod.trim();
    return (
      gstr1Runs.find((r) => (r.period || "").trim() === norm) ||
      gstr1Runs.find((r) => (r.period || "").startsWith(norm)) ||
      null
    );
  }, [gstr1Runs, taxPeriod]);

  const tieOutHref = matchingGstr1
    ? `/reconcile/gstr1/results?run_id=${encodeURIComponent(matchingGstr1.id)}`
    : clientGstinId
      ? `/reconcile/gstr1/new?client_gstin_id=${encodeURIComponent(clientGstinId)}`
      : "/reconcile/gstr1/new";

  return (
    <div className="rounded-xl border border-[#E5E7EB] px-4 py-3">
      <p className="text-[12px] font-semibold text-gray-800">Related checks</p>
      <ul className="mt-2 space-y-1.5 text-[12px]">
        <li>
          <Link
            href={`/reconcile/runs/${encodeURIComponent(runId)}/results`}
            className="font-medium text-gray-700 underline-offset-2 hover:underline"
          >
            Purchase reconciliation results
          </Link>
          <span className="text-gray-400"> — matched / missed ITC / risk</span>
        </li>
        {showStandaloneLink ? (
          <li>
            <Link
              href={`/reconcile/runs/${encodeURIComponent(runId)}/gstr3b`}
              className="font-medium text-gray-700 underline-offset-2 hover:underline"
            >
              Open full GSTR-3B summary page
            </Link>
          </li>
        ) : null}
        <li>
          <Link
            href={tieOutHref}
            className="font-medium text-gray-700 underline-offset-2 hover:underline"
          >
            {matchingGstr1
              ? "GSTR-1 vs 3B tie-out (Table 3.1a)"
              : "Start / open GSTR-1 reconcile for tie-out"}
          </Link>
          <span className="text-gray-400">
            {matchingGstr1
              ? ` — period ${matchingGstr1.period || taxPeriod}`
              : " — no matching GSTR-1 run for this period yet"}
          </span>
        </li>
      </ul>
    </div>
  );
}

export function Gstr3bSummaryView({
  runId,
  authToken,
  variant = "embedded",
}: {
  runId: string;
  authToken: string;
  /** embedded = results tab; page = dedicated route */
  variant?: "embedded" | "page";
}) {
  const [uploading, setUploading] = useState(false);
  const [uploadError, setUploadError] = useState<string | null>(null);
  const reuploadRef = useRef<HTMLInputElement>(null);

  const { data, error, mutate, isLoading } = useSWR<Gstr3bReconciliationResult>(
    authToken ? [`gstr3b`, runId] : null,
    () => gstr3bApi.get(authToken, runId),
    { shouldRetryOnError: false }
  );

  const handleFile = useCallback(
    async (file: File) => {
      setUploading(true);
      setUploadError(null);
      try {
        const result = await gstr3bApi.upload(authToken, runId, file);
        await mutate(result, false);
      } catch (err: unknown) {
        let msg = "Upload failed. Please try again.";
        if (isApiError(err)) msg = err.detail || msg;
        else if (err instanceof Error) msg = err.message;
        else if (typeof err === "string") msg = err;
        setUploadError(msg);
      } finally {
        setUploading(false);
      }
    },
    [authToken, runId, mutate]
  );

  const hasResult = !!data && !error;
  const notFound = !!error && (error as { status?: number })?.status === 404;
  const fetchFailed = !!error && !notFound;
  const filed = data?.filed ?? null;
  const periodLabel = data ? formatPeriod(data.tax_period) : "";

  return (
    <div className={variant === "page" ? "space-y-5" : sectionContainerClass}>
      {variant === "embedded" ? (
        <SectionHeader title="GSTR-3B summary" dotColor="#111111" />
      ) : null}

      {isLoading && !data && !error && (
        <div className="flex flex-col items-center justify-center py-16 gap-3">
          <svg className="h-8 w-8 animate-spin text-brand" fill="none" viewBox="0 0 24 24">
            <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
            <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8v8z" />
          </svg>
          <p className="text-[13px] text-gray-400">Loading GSTR-3B…</p>
        </div>
      )}

      {fetchFailed && (
        <p className="text-[13px] text-red-500">
          Failed to load GSTR-3B data. Please refresh and try again.
        </p>
      )}

      {(notFound || (!data && !error && !isLoading)) && !uploading && (
        <UploadArea onFile={handleFile} loading={uploading} error={uploadError} />
      )}

      {uploading && !hasResult && (
        <div className="flex flex-col items-center justify-center py-16 gap-3">
          <svg className="h-8 w-8 animate-spin text-brand" fill="none" viewBox="0 0 24 24">
            <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
            <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8v8z" />
          </svg>
          <p className="text-[13px] text-gray-400">Processing GSTR-3B…</p>
        </div>
      )}

      {hasResult && data && (
        <div className="space-y-5">
          <div className="flex w-full flex-wrap items-center justify-between gap-3">
            <div className="flex flex-wrap items-center gap-3">
              <h2 className="text-lg font-semibold text-gray-900">
                GSTR-3B — {periodLabel}
              </h2>
              <StatusBadge status={data.overall_status} />
              <span className="text-[12px] text-gray-400 tabular-nums">
                {data.client_gstin}
              </span>
            </div>
            <div>
              <input
                ref={reuploadRef}
                type="file"
                accept=".json"
                className="hidden"
                onChange={(e) => {
                  const f = e.target.files?.[0];
                  if (f) handleFile(f);
                }}
              />
              <button
                type="button"
                disabled={uploading}
                onClick={() => reuploadRef.current?.click()}
                className="inline-flex items-center gap-1.5 rounded-xl border border-[#E5E7EB] bg-white px-3 py-1.5 text-[12px] font-medium text-gray-600 hover:bg-gray-50 disabled:opacity-50"
              >
                {uploading ? "Uploading…" : "Re-upload GSTR-3B"}
              </button>
            </div>
          </div>

          {uploadError && <p className="text-[12px] text-red-500">{uploadError}</p>}

          {/* 1. DRC-01C — most actionable */}
          {data.drc01c ? (
            <Drc01cBanner drc={data.drc01c} />
          ) : (
            <div className="rounded-xl border border-[#E5E7EB] bg-[#FAFAFA] px-4 py-3 text-[12px] text-gray-500">
              DRC-01C threshold not available for this result.
            </div>
          )}

          {/* 2. 2B vs 3B ITC check */}
          <div>
            <div className="mb-3">
              <p className="text-[13px] font-semibold text-gray-800">
                ITC claimed vs GSTR-2B available
              </p>
              <p className="mt-1 text-[12px] text-gray-500 leading-relaxed">
                Net difference = GSTR-3B claimed (Table 4C net) − all GSTR-2B available ITC
                (positive = overclaimed, negative = underclaimed). Not the same as GSTR-9C FY
                Rollup variance, which uses clean-matched 2B ITC only.
              </p>
            </div>
            <div className={statCardsGridClass}>
              <StatCard
                label="GSTR-2B ITC Available"
                accent="neutral"
                value={
                  <CompactStatAmount amount={data.total.gstr2b} className="text-gray-800" />
                }
              />
              <StatCard
                label="GSTR-3B ITC Claimed"
                accent="neutral"
                value={
                  <CompactStatAmount amount={data.total.gstr3b} className="text-gray-800" />
                }
              />
              <StatCard
                label="Net difference (3B claimed − all 2B)"
                accent={
                  data.total.difference === 0
                    ? "matched"
                    : data.total.difference > 0
                      ? "risk"
                      : "pending"
                }
                emphasis={data.total.difference === 0 ? "default" : "attention"}
                value={
                  <span className={`inline-flex items-baseline gap-0.5 ${diffColor(data.total.difference)}`}>
                    {data.total.difference > 0 ? <span aria-hidden>+</span> : null}
                    {data.total.difference < 0 ? <span aria-hidden>−</span> : null}
                    <CompactStatAmount
                      amount={Math.abs(data.total.difference)}
                      className={diffColor(data.total.difference)}
                    />
                  </span>
                }
              />
            </div>
            {data.overall_status === "MIXED" ? (
              <p className="mt-3 text-[12px] text-violet-800/90 leading-relaxed">
                Mixed by tax head — some heads are overclaimed and others underclaimed.
                Use the net difference above for the overall position.
              </p>
            ) : null}
            <div className="mt-4">
              <ComparisonTable result={data} />
            </div>
          </div>

          {/* 3. ITC by source — full prominence */}
          {filed ? (
            <div>
              <p className="mb-3 text-[13px] font-semibold text-gray-800">
                Table 4 — ITC available by source
              </p>
              <ItcBySourceTable filed={filed} />
            </div>
          ) : (
            <div className="rounded-xl border border-[#E5E7EB] bg-[#FAFAFA] px-4 py-3 text-[12px] text-gray-500">
              Filed breakdown unavailable (raw GSTR-3B could not be re-parsed). ITC check above
              still reflects claimed vs 2B totals.
            </div>
          )}

          {/* 4. 3.1(a) */}
          {filed ? (
            <div>
              <p className="mb-3 text-[13px] font-semibold text-gray-800">
                Table 3.1(a) — Outward taxable supplies
              </p>
              <SupplyRowTable
                label="3.1(a) Other than zero-rated / nil / exempt"
                row={{
                  taxable_value: filed.outward_supply.taxable_value,
                  igst: filed.outward_supply.igst,
                  cgst: filed.outward_supply.cgst ?? 0,
                  sgst: filed.outward_supply.sgst ?? 0,
                  cess: filed.outward_supply.cess ?? 0,
                }}
                emphasize
              />
            </div>
          ) : null}

          {/* 5. Secondary accordion */}
          {filed ? <SecondaryFiledAccordion filed={filed} /> : null}

          {/* 6. Related */}
          <RelatedChecks
            runId={runId}
            authToken={authToken}
            clientGstinId={data.client_gstin_id}
            taxPeriod={data.tax_period}
            showStandaloneLink={variant === "embedded"}
          />

          <p className="text-[11px] italic text-gray-300">
            Based on the GSTR-3B JSON you uploaded. ReconDesk does not connect to the GST portal
            directly. Verify figures before filing amendments or responding to intimations.
          </p>
        </div>
      )}
    </div>
  );
}
