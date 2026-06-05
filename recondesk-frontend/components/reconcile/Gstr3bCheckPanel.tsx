"use client";

import { useCallback, useRef, useState } from "react";
import useSWR from "swr";

import type { Gstr3bReconciliationResult, Gstr3bHeadResult } from "@/lib/api";
import { gstr3bApi } from "@/lib/api";
import { formatINR } from "@/lib/format";
import { SectionHeader, sectionContainerClass, StatCard, statCardsGridClass } from "./ResultsUi";

// ─── Helpers ──────────────────────────────────────────────────────────────────

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
  const abs = Math.abs(diff);
  return (
    <span className={`tabular-nums font-semibold ${diffColor(diff)}`}>
      {sign}{formatINR(abs)}
    </span>
  );
}

// ─── Status explanation ───────────────────────────────────────────────────────

function StatusExplanation({ status }: { status: string }) {
  if (status === "OVERCLAIMED") {
    return (
      <p className="mt-4 text-[12px] italic text-gray-400">
        ITC claimed in GSTR-3B exceeds what is available in GSTR-2B. This may attract interest
        under Section 50 and penalty. Consider filing an amendment.
      </p>
    );
  }
  if (status === "UNDERCLAIMED") {
    return (
      <p className="mt-4 text-[12px] italic text-gray-400">
        ITC available in GSTR-2B has not been fully claimed. You may amend GSTR-3B to recover the
        remaining ITC before the due date.
      </p>
    );
  }
  return (
    <p className="mt-4 text-[12px] italic text-gray-400">
      ITC claimed in GSTR-3B matches GSTR-2B available ITC. No action required.
    </p>
  );
}

// ─── Comparison table ─────────────────────────────────────────────────────────

function ComparisonTable({ result }: { result: Gstr3bReconciliationResult }) {
  const rows: { label: string; head: Gstr3bHeadResult }[] = [
    { label: "IGST", head: result.igst },
    { label: "CGST", head: result.cgst },
    { label: "SGST", head: result.sgst },
    { label: "Total", head: result.total },
  ];

  return (
    <div className="mt-5 overflow-x-auto rounded-xl border border-[#F0F0F0]">
      <table className="w-full table-fixed border-collapse text-left text-[13px]">
        <colgroup>
          <col style={{ width: "14%" }} />
          <col style={{ width: "22%" }} />
          <col style={{ width: "22%" }} />
          <col style={{ width: "22%" }} />
          <col style={{ width: "20%" }} />
        </colgroup>
        <thead className="bg-[#FAFAFA] text-[11px] font-semibold uppercase tracking-wider text-gray-400">
          <tr>
            <th className="px-4 py-3 text-left">Tax Head</th>
            <th className="px-4 py-3 text-right">GSTR-2B Available</th>
            <th className="px-4 py-3 text-right">GSTR-3B Claimed</th>
            <th className="px-4 py-3 text-right">Difference</th>
            <th className="px-4 py-3 text-left">Status</th>
          </tr>
        </thead>
        <tbody>
          {rows.map(({ label, head }, i) => (
            <tr
              key={label}
              className={`border-t border-[#F5F5F5] ${
                i === rows.length - 1 ? "bg-[#FAFAFA] font-semibold" : "bg-white"
              } hover:bg-[#FAFAFA] transition-all duration-150`}
            >
              <td className="px-4 py-3 text-gray-700">{label}</td>
              <td className="px-4 py-3 text-right tabular-nums text-gray-800">
                {formatINR(head.gstr2b)}
              </td>
              <td className="px-4 py-3 text-right tabular-nums text-gray-800">
                {formatINR(head.gstr3b)}
              </td>
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

// ─── Upload area ──────────────────────────────────────────────────────────────

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
        onDragOver={(e) => { e.preventDefault(); setDragging(true); }}
        onDragLeave={() => setDragging(false)}
        onDrop={(e) => { e.preventDefault(); setDragging(false); handleFiles(e.dataTransfer.files); }}
        className={`flex w-full max-w-lg flex-col items-center justify-center gap-4 rounded-2xl border-2 border-dashed px-8 py-12 text-center transition-colors ${
          dragging ? "border-brand bg-brand/5" : "border-[#E5E7EB] bg-[#FAFAFA]"
        }`}
      >
        <div className="flex h-12 w-12 items-center justify-center rounded-full bg-white shadow-sm ring-1 ring-[#E5E7EB]">
          <svg className="h-5 w-5 text-gray-400" fill="none" stroke="currentColor" strokeWidth={1.5} viewBox="0 0 24 24">
            <path strokeLinecap="round" strokeLinejoin="round" d="M19.5 14.25v-2.625a3.375 3.375 0 0 0-3.375-3.375h-1.5A1.125 1.125 0 0 1 13.5 7.125v-1.5a3.375 3.375 0 0 0-3.375-3.375H8.25m6.75 12-3-3m0 0-3 3m3-3v6m-1.5-15H5.625c-.621 0-1.125.504-1.125 1.125v17.25c0 .621.504 1.125 1.125 1.125h12.75c.621 0 1.125-.504 1.125-1.125V11.25a9 9 0 0 0-9-9Z" />
          </svg>
        </div>
        <div>
          <p className="text-[14px] font-medium text-gray-800">
            Upload GSTR-3B JSON to verify ITC claimed
          </p>
          <p className="mt-1.5 text-[12px] text-gray-400 leading-relaxed">
            Download GSTR-3B JSON from GST Portal → Returns → GSTR-3B → View Filed Returns → Download JSON
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
          className="mt-2 inline-flex items-center gap-2 rounded-xl bg-brand px-5 py-2.5 text-[13px] font-medium text-white shadow-sm hover:bg-brand/90 active:bg-brand/80 disabled:cursor-not-allowed disabled:opacity-50 transition-all duration-150"
        >
          {loading ? (
            <>
              <svg className="h-4 w-4 animate-spin" fill="none" viewBox="0 0 24 24">
                <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
                <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8v8z" />
              </svg>
              Uploading…
            </>
          ) : (
            <>
              <svg className="h-4 w-4" fill="none" stroke="currentColor" strokeWidth={2} viewBox="0 0 24 24">
                <path strokeLinecap="round" strokeLinejoin="round" d="M3 16.5v2.25A2.25 2.25 0 0 0 5.25 21h13.5A2.25 2.25 0 0 0 21 18.75V16.5m-13.5-9L12 3m0 0 4.5 4.5M12 3v13.5" />
              </svg>
              Upload GSTR-3B JSON
            </>
          )}
        </button>
        {error && (
          <p className="mt-1 text-[12px] text-red-500">{error}</p>
        )}
      </div>
    </div>
  );
}

// ─── Loaded state ─────────────────────────────────────────────────────────────

function Gstr3bLoaded({
  result,
  onReupload,
  reuploadLoading,
  reuploadError,
  onFile,
}: {
  result: Gstr3bReconciliationResult;
  onReupload: () => void;
  reuploadLoading: boolean;
  reuploadError: string | null;
  onFile: (f: File) => void;
}) {
  const inputRef = useRef<HTMLInputElement>(null);
  const periodLabel = formatPeriod(result.tax_period);

  return (
    <div>
      {/* Header row */}
      <div className="mb-5 flex w-full flex-wrap items-center justify-between gap-3">
        <div className="flex items-center gap-3">
          <div className="flex items-center gap-2">
            <span className="h-2 w-2 shrink-0 rounded-full bg-purple-500" />
            <h2 className="text-lg font-semibold text-gray-900">
              GSTR-3B Verification — {periodLabel}
            </h2>
          </div>
          <StatusBadge status={result.overall_status} />
        </div>
        <div className="flex items-center gap-2">
          <input
            ref={inputRef}
            type="file"
            accept=".json"
            className="hidden"
            onChange={(e) => {
              const f = e.target.files?.[0];
              if (f) onFile(f);
            }}
          />
          <button
            type="button"
            disabled={reuploadLoading}
            onClick={() => inputRef.current?.click()}
            className="inline-flex items-center gap-1.5 rounded-xl border border-[#E5E7EB] bg-white px-3 py-1.5 text-[12px] font-medium text-gray-600 hover:bg-gray-50 disabled:opacity-50 transition-all duration-150"
          >
            {reuploadLoading ? "Uploading…" : "Re-upload GSTR-3B"}
          </button>
        </div>
      </div>

      {reuploadError && (
        <p className="mb-3 text-[12px] text-red-500">{reuploadError}</p>
      )}

      {/* Summary stat cards */}
      <div className={statCardsGridClass}>
        <StatCard
          label="GSTR-2B ITC Available"
          accent="neutral"
          value={
            <span className="inline-flex tabular-nums text-xl font-semibold">
              <span className="text-gray-400">₹</span>
              <span className="text-gray-800">{result.total.gstr2b.toLocaleString("en-IN", { minimumFractionDigits: 2, maximumFractionDigits: 2 })}</span>
            </span>
          }
        />
        <StatCard
          label="GSTR-3B ITC Claimed"
          accent="neutral"
          value={
            <span className="inline-flex tabular-nums text-xl font-semibold">
              <span className="text-gray-400">₹</span>
              <span className="text-gray-800">{result.total.gstr3b.toLocaleString("en-IN", { minimumFractionDigits: 2, maximumFractionDigits: 2 })}</span>
            </span>
          }
        />
        <StatCard
          label="Net Difference"
          accent={
            result.total.difference === 0
              ? "matched"
              : result.total.difference > 0
              ? "risk"
              : "pending"
          }
          value={
            <span className={`inline-flex tabular-nums text-xl font-semibold ${diffColor(result.total.difference)}`}>
              {result.total.difference > 0 ? "+" : result.total.difference < 0 ? "−" : ""}
              {formatINR(Math.abs(result.total.difference))}
            </span>
          }
        />
      </div>

      {/* Comparison table */}
      <ComparisonTable result={result} />

      {/* Status explanation */}
      <StatusExplanation status={result.overall_status} />

      {/* Disclaimer */}
      <p className="mt-6 text-[11px] italic text-gray-300">
        This comparison is based on data uploaded by the CA. ReconDesk does not connect to the GST portal directly. Verify figures before filing amendments.
      </p>
    </div>
  );
}

// ─── Main panel ───────────────────────────────────────────────────────────────

export function Gstr3bCheckPanel({
  runId,
  authToken,
}: {
  runId: string;
  authToken: string;
}) {
  const [uploading, setUploading] = useState(false);
  const [uploadError, setUploadError] = useState<string | null>(null);

  const { data, error, mutate } = useSWR<Gstr3bReconciliationResult>(
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
        const msg =
          err instanceof Error
            ? err.message
            : typeof err === "string"
            ? err
            : "Upload failed. Please try again.";
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

  return (
    <div className={sectionContainerClass}>
      <SectionHeader
        title="GSTR-3B ITC Check"
        dotColor="#7C3AED"
      />

      {fetchFailed && (
        <p className="text-[13px] text-red-500">
          Failed to load GSTR-3B data. Please refresh and try again.
        </p>
      )}

      {(notFound || (!data && !error)) && !uploading && (
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

      {hasResult && (
        <Gstr3bLoaded
          result={data}
          onReupload={() => {}}
          reuploadLoading={uploading}
          reuploadError={uploadError}
          onFile={handleFile}
        />
      )}
    </div>
  );
}
