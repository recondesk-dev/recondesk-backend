"use client";

import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { Suspense, useCallback, useState } from "react";
import { Loader2 } from "lucide-react";

import {
  RegisterTypeDetectionBanner,
} from "@/components/reconcile/TallyRegisterImportHints";
import { isApiError, registerUploadApi, type RegisterTypeDetection } from "@/lib/api";
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

function Gstr1ReconcileNewContent() {
  const router = useRouter();
  const searchParams = useSearchParams();
  const clientGstinId = searchParams.get("client_gstin_id")?.trim() || null;
  const tokenState = useAccessToken();
  const token =
    typeof tokenState === "string" && tokenState.length > 0 ? tokenState : null;
  const [srFile, setSrFile] = useState<File | null>(null);
  const [gstr1File, setGstr1File] = useState<File | null>(null);
  const [gstr3bFile, setGstr3bFile] = useState<File | null>(null);
  const [priorGstr1File, setPriorGstr1File] = useState<File | null>(null);
  const [filingPeriod, setFilingPeriod] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [running, setRunning] = useState(false);
  const [detectBusy, setDetectBusy] = useState(false);
  const [registerTypeDetection, setRegisterTypeDetection] =
    useState<RegisterTypeDetection | null>(null);
  const [registerTypeOverride, setRegisterTypeOverride] = useState<
    "purchase" | "sales" | null
  >(null);

  const registerTypeBlocksSubmit =
    !!registerTypeDetection &&
    registerTypeOverride !== "sales" &&
    (registerTypeDetection.requires_manual_choice ||
      registerTypeDetection.register_type === "ambiguous" ||
      (!!registerTypeDetection.pipeline_mismatch &&
        registerTypeDetection.register_type === "purchase"));

  const canSubmit = Boolean(
    token &&
      srFile &&
      gstr1File &&
      gstr3bFile &&
      !running &&
      !detectBusy &&
      !registerTypeBlocksSubmit
  );

  const onSrFileChange = useCallback(
    async (file: File | null) => {
      setSrFile(file);
      setRegisterTypeDetection(null);
      setRegisterTypeOverride(null);
      setError(null);
      if (!file || !token) return;
      if (!/\.(xlsx|xls|csv)$/i.test(file.name)) {
        setError("Sales Register must be .xlsx, .xls, or .csv");
        return;
      }
      if (file.size > MAX_XLSX) {
        setError("Sales Register exceeds the 20 MB limit");
        return;
      }
      setDetectBusy(true);
      try {
        const det = await registerUploadApi.detectType(token, file, {
          expectedType: "sales",
          clientGstinId: clientGstinId ?? undefined,
        });
        setRegisterTypeDetection({
          ...det,
          pipeline_mismatch:
            det.register_type === "purchase" &&
            (det.confidence === "high" || det.confidence === "medium"),
        });
      } catch (err) {
        // Soft-fail: still allow upload; type banner just won't show.
        if (isApiError(err)) {
          console.warn("register detect-type failed:", err.detail);
        }
      } finally {
        setDetectBusy(false);
      }
    },
    [token, clientGstinId]
  );

  const onRegisterTypeOverride = (type: "purchase" | "sales") => {
    if (type === "purchase") {
      const href = clientGstinId
        ? `/reconcile/${encodeURIComponent(clientGstinId)}/new`
        : "/clients";
      router.push(href);
      return;
    }
    setRegisterTypeOverride("sales");
  };

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
    if (priorGstr1File && !/\.json$/i.test(priorGstr1File.name)) {
      setError("Prior period GSTR-1 must be a .json file");
      return;
    }
    if (
      srFile.size > MAX_XLSX ||
      gstr1File.size > MAX_JSON ||
      gstr3bFile.size > MAX_JSON ||
      (priorGstr1File != null && priorGstr1File.size > MAX_JSON)
    ) {
      setError("One or more files exceed the 20 MB limit");
      return;
    }
    if (registerTypeBlocksSubmit) {
      setError(
        "Confirm this file is a Sales Register (or open the Purchase / GSTR-2B import) before running."
      );
      return;
    }

    setRunning(true);
    try {
      const result = await runGstr1Reconcile({
        salesRegisterFile: srFile,
        gstr1JsonFile: gstr1File,
        gstr3bJsonFile: gstr3bFile,
        priorGstr1JsonFile: priorGstr1File,
        gstr1FilingPeriod: filingPeriod.trim() || null,
        clientGstinId,
        token,
      });
      // Session storage = fast path for immediate redirect; DB is source of truth.
      persistGstr1Result(result);
      if (result.run_id) {
        router.push(
          `/reconcile/gstr1/results?run_id=${encodeURIComponent(result.run_id)}`
        );
      } else {
        router.push("/reconcile/gstr1/results");
      }
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
  }, [
    token,
    srFile,
    gstr1File,
    gstr3bFile,
    priorGstr1File,
    filingPeriod,
    clientGstinId,
    router,
    registerTypeBlocksSubmit,
  ]);

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
          invoices, classify G1M1–G1M11 mismatches, summarise Table 13 documents
          issued, detect Tables 9A/9B/9C amendments when a prior GSTR-1 is
          provided, and tie out outward supplies against Table 3.1(a).
        </p>
      </div>

      <div className="space-y-3">
        <FileField
          label="Sales Register"
          hint=".xlsx / .xls / .csv — Tally Sales Register or other books of account (outward supplies)"
          accept=".xlsx,.xls,.csv,application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
          file={srFile}
          onChange={(f) => void onSrFileChange(f)}
        />
        {detectBusy ? (
          <p className="px-1 text-[12px] text-gray-500">Detecting register type…</p>
        ) : null}
        {registerTypeDetection ? (
          <RegisterTypeDetectionBanner
            detection={registerTypeDetection}
            expectedType="sales"
            clientId={clientGstinId}
            overridden={registerTypeOverride === "sales"}
            onOverride={onRegisterTypeOverride}
            onClearOverride={() => setRegisterTypeOverride(null)}
            busy={detectBusy}
          />
        ) : (
          <details className="rounded-[1.25rem] bg-white px-5 py-4 text-[12px] text-gray-600 shadow-[var(--shadow-soft)] ring-1 ring-[#F0F0F0]">
            <summary className="cursor-pointer text-[13px] font-semibold text-[var(--ink)]">
              How to export from Tally (Sales Register)
            </summary>
            <p className="mt-2 leading-relaxed">
              In TallyPrime: Gateway of Tally → Display More Reports → Statutory
              Reports → GST → GSTR-1 / Sales Register → set period → Alt+E (Export) →
              Excel or CSV. In Tally ERP 9: Gateway of Tally → Display → Statutory
              Reports → GST → GSTR-1 → Export. Prefer a columnar register that includes
              GSTIN/UIN, Taxable Amt, and Invoice Type (B2B/B2C) when available.
            </p>
          </details>
        )}
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
        <FileField
          label="Prior Period GSTR-1 JSON (optional — for amendment detection)"
          hint=".json — previously filed GSTR-1 used to detect Tables 9A / 9B / 9C amendments"
          accept=".json,application/json"
          file={priorGstr1File}
          onChange={setPriorGstr1File}
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

export default function Gstr1ReconcileNewPage() {
  return (
    <Suspense
      fallback={
        <div className="flex min-h-[40vh] items-center justify-center px-8 text-[13px] text-gray-500">
          Loading…
        </div>
      }
    >
      <Gstr1ReconcileNewContent />
    </Suspense>
  );
}
