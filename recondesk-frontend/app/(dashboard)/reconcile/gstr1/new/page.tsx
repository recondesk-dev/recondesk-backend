"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useCallback, useState } from "react";
import { Loader2 } from "lucide-react";

import { isApiError } from "@/lib/api";
import {
  persistGstr1Result,
  runGstr1Reconcile,
} from "@/lib/gstr1Reconcile";
import { useAccessToken } from "@/lib/hooks/useAccessToken";

const MAX_XLSX = 20 * 1024 * 1024;
const MAX_JSON = 20 * 1024 * 1024;

function FileField({
  label,
  hint,
  accept,
  file,
  onChange,
}: {
  label: string;
  hint: string;
  accept: string;
  file: File | null;
  onChange: (f: File | null) => void;
}) {
  return (
    <label className="block rounded-[1.25rem] bg-white p-5 shadow-[var(--shadow-soft)] ring-1 ring-[#F0F0F0]">
      <span className="text-[13px] font-semibold text-[var(--ink)]">{label}</span>
      <span className="mt-1 block text-[12px] text-gray-500">{hint}</span>
      <input
        type="file"
        accept={accept}
        className="mt-3 block w-full text-[13px] text-gray-600 file:mr-3 file:rounded-full file:border-0 file:bg-[#F5F5F6] file:px-4 file:py-2 file:text-[13px] file:font-semibold file:text-gray-700 hover:file:bg-gray-200/70"
        onChange={(e) => onChange(e.target.files?.[0] ?? null)}
      />
      {file ? (
        <p className="mt-2 truncate text-[12px] text-gray-500">
          {file.name} · {(file.size / 1024).toFixed(1)} KB
        </p>
      ) : null}
    </label>
  );
}

export default function Gstr1ReconcileNewPage() {
  const router = useRouter();
  const tokenState = useAccessToken();
  const token =
    typeof tokenState === "string" && tokenState.length > 0 ? tokenState : null;
  const [srFile, setSrFile] = useState<File | null>(null);
  const [gstr1File, setGstr1File] = useState<File | null>(null);
  const [gstr3bFile, setGstr3bFile] = useState<File | null>(null);
  const [filingPeriod, setFilingPeriod] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [running, setRunning] = useState(false);

  const canSubmit = Boolean(token && srFile && gstr1File && gstr3bFile && !running);

  const onSubmit = useCallback(async () => {
    if (!token || !srFile || !gstr1File || !gstr3bFile) return;
    setError(null);

    if (!/\.(xlsx|xls|csv)$/i.test(srFile.name)) {
      setError("Sales Register must be .xlsx, .xls, or .csv");
      return;
    }
    if (!/\.json$/i.test(gstr1File.name) || !/\.json$/i.test(gstr3bFile.name)) {
      setError("GSTR-1 and GSTR-3B must be .json files");
      return;
    }
    if (srFile.size > MAX_XLSX || gstr1File.size > MAX_JSON || gstr3bFile.size > MAX_JSON) {
      setError("One or more files exceed the 20 MB limit");
      return;
    }

    setRunning(true);
    try {
      const result = await runGstr1Reconcile({
        salesRegisterFile: srFile,
        gstr1JsonFile: gstr1File,
        gstr3bJsonFile: gstr3bFile,
        gstr1FilingPeriod: filingPeriod.trim() || null,
        token,
      });
      persistGstr1Result(result);
      router.push("/reconcile/gstr1/results");
    } catch (err) {
      if (isApiError(err)) {
        setError(err.detail || `Request failed (${err.status})`);
      } else if (err instanceof Error) {
        setError(err.message);
      } else {
        setError("GSTR-1 reconciliation failed");
      }
    } finally {
      setRunning(false);
    }
  }, [token, srFile, gstr1File, gstr3bFile, filingPeriod, router]);

  return (
    <div className="mx-auto w-full max-w-3xl px-8 py-8">
      <div className="mb-6">
        <p className="text-[11px] font-medium uppercase tracking-widest text-gray-400">
          Sales Reconciliation
        </p>
        <h1 className="mt-1 text-2xl font-semibold tracking-tight text-[var(--ink)]">
          GSTR-1 Check
        </h1>
        <p className="mt-2 text-[14px] leading-relaxed text-gray-500">
          Upload your Sales Register, GSTR-1 JSON, and GSTR-3B JSON. We match
          invoices, classify G1M1–G1M6 mismatches, and tie out outward supplies
          against Table 3.1(a).
        </p>
      </div>

      <div className="space-y-3">
        <FileField
          label="Sales Register"
          hint=".xlsx / .xls / .csv — books of account (outward supplies)"
          accept=".xlsx,.xls,.csv,application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
          file={srFile}
          onChange={setSrFile}
        />
        <FileField
          label="GSTR-1 JSON"
          hint="Portal download or API response for the filing period"
          accept=".json,application/json"
          file={gstr1File}
          onChange={setGstr1File}
        />
        <FileField
          label="GSTR-3B JSON"
          hint="Used for Table 3.1(a) outward supply tie-out"
          accept=".json,application/json"
          file={gstr3bFile}
          onChange={setGstr3bFile}
        />

        <label className="block rounded-[1.25rem] bg-white p-5 shadow-[var(--shadow-soft)] ring-1 ring-[#F0F0F0]">
          <span className="text-[13px] font-semibold text-[var(--ink)]">
            Filing period (optional)
          </span>
          <span className="mt-1 block text-[12px] text-gray-500">
            MMYYYY — e.g. 042025. Auto-detected from GSTR-1 when omitted.
          </span>
          <input
            type="text"
            inputMode="numeric"
            placeholder="042025"
            maxLength={6}
            value={filingPeriod}
            onChange={(e) => setFilingPeriod(e.target.value.replace(/\D/g, "").slice(0, 6))}
            className="mt-3 h-10 w-full max-w-[160px] rounded-full border-0 bg-[#F5F5F6] px-4 text-[13px] font-medium text-gray-700 outline-none focus:ring-2 focus:ring-black/10"
          />
        </label>
      </div>

      {error ? (
        <div
          className="mt-4 rounded-[1.25rem] bg-red-50 px-5 py-4 text-sm text-red-900"
          role="alert"
        >
          {error}
        </div>
      ) : null}

      <div className="mt-6 flex flex-wrap items-center gap-3">
        <button
          type="button"
          disabled={!canSubmit}
          onClick={() => void onSubmit()}
          className="inline-flex min-h-[44px] items-center justify-center gap-2 rounded-full bg-[var(--ink)] px-6 text-[13px] font-semibold text-white transition-opacity hover:opacity-90 disabled:cursor-not-allowed disabled:opacity-40"
        >
          {running ? (
            <>
              <Loader2 className="h-4 w-4 animate-spin" />
              Running reconciliation…
            </>
          ) : (
            "Run GSTR-1 Check"
          )}
        </button>
        <Link
          href="/clients"
          className="inline-flex min-h-[44px] items-center justify-center rounded-full bg-[#F5F5F6] px-5 text-[13px] font-semibold text-gray-700 transition-colors hover:bg-gray-200/70"
        >
          Cancel
        </Link>
      </div>
    </div>
  );
}
