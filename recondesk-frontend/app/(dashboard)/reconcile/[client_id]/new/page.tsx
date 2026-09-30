"use client";
import { Analytics } from "@/lib/analytics";

import Link from "next/link";
import { useParams, useRouter, useSearchParams } from "next/navigation";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Loader2 } from "lucide-react";
import {
  clientsApi,
  gstnApi,
  importWizardApi,
  prUploadApi,
  type ApiError,
  type ClientGstin,
  type ClientImportMappingItem,
  type ColumnMappingRow,
  type ImportTargetField,
  type ImportWizardRun,
  type RegisterTypeDetection,
  type SanityCheckItem,
} from "@/lib/api";
import { isGstnConnected } from "@/components/clients/ConnectGstnModal";
import {
  RegisterTypeDetectionBanner,
} from "@/components/reconcile/TallyRegisterImportHints";
import { FileDropzone } from "@/components/ui/FileDropzone";
import { createClient, subscribeAccessToken } from "@/lib/supabase/client";

const MAX_UPLOAD = 20 * 1024 * 1024;
const ACTIVE_STATUSES = ["draft", "gstr_uploaded", "pr_uploaded", "pending", "processing"] as const;
const TERMINAL_STATUSES = ["complete", "cancelled", "error"] as const;

function isTerminalWizardStatus(status: string | null | undefined): boolean {
  return (TERMINAL_STATUSES as readonly string[]).includes(String(status || ""));
}

const REQUIRED_MAPPING_FIELDS = [
  "gstin",
  "invoice_number",
  "invoice_date",
  "taxable_value",
] as const;

const TAX_MAPPING_FIELDS = ["cgst", "sgst", "igst", "cess"] as const;

const OPTIONAL_MAPPING_FIELDS = ["total_tax", "supplier_name"] as const;

const IMPORT_TARGET_FIELDS: ImportTargetField[] = [
  "gstin",
  "invoice_number",
  "invoice_date",
  "taxable_value",
  "cgst",
  "sgst",
  "igst",
  "cess",
];

const MAPPING_FIELD_LABELS: Record<string, string> = {
  gstin: "GSTIN",
  invoice_number: "Invoice number",
  invoice_date: "Invoice date",
  taxable_value: "Taxable value",
  cgst: "CGST",
  sgst: "SGST",
  igst: "IGST",
  cess: "Cess",
  total_tax: "Total tax",
  supplier_name: "Supplier name",
};

function isOptionalMappingField(field: string): boolean {
  return (OPTIONAL_MAPPING_FIELDS as readonly string[]).includes(field);
}

function isTaxMapped(headerToTarget: Record<string, ImportTargetField | "">): boolean {
  const targets = new Set(Object.values(headerToTarget).filter(Boolean));
  return TAX_MAPPING_FIELDS.some((t) => targets.has(t));
}

function requiredTargetsMapped(
  headerToTarget: Record<string, ImportTargetField | "">
): boolean {
  const targets = new Set(Object.values(headerToTarget).filter(Boolean));
  return REQUIRED_MAPPING_FIELDS.every((f) => targets.has(f));
}

function formatBytes(n: number | null | undefined): string {
  if (n == null || Number.isNaN(n)) return "—";
  if (n < 1024) return `${n} B`;
  if (n < 1024 * 1024) return `${(n / 1024).toFixed(1)} KB`;
  return `${(n / (1024 * 1024)).toFixed(2)} MB`;
}

async function sha256Hex(file: File): Promise<string> {
  const buf = await file.arrayBuffer();
  const hash = await crypto.subtle.digest("SHA-256", buf);
  return Array.from(new Uint8Array(hash))
    .map((b) => b.toString(16).padStart(2, "0"))
    .join("");
}

const MONTH_NAMES = [
  "January",
  "February",
  "March",
  "April",
  "May",
  "June",
  "July",
  "August",
  "September",
  "October",
  "November",
  "December",
];

function pastMonthOptions(): { value: string; label: string }[] {
  const out: { value: string; label: string }[] = [];
  const d = new Date();
  let y = d.getFullYear();
  let m = d.getMonth();
  const fmt = new Intl.DateTimeFormat("en-IN", { month: "long", year: "numeric" });
  for (let i = 0; i < 18; i++) {
    const mm = String(m + 1).padStart(2, "0");
    const value = `${y}-${mm}-01`;
    const label = `${fmt.format(new Date(y, m, 1))}${i === 0 ? " (Current)" : ""}`;
    out.push({ value, label });
    m -= 1;
    if (m < 0) {
      m = 11;
      y -= 1;
    }
  }
  return out;
}

function periodLabel(iso: string): string {
  const [y, mo] = iso.slice(0, 10).split("-");
  return new Intl.DateTimeFormat("en-IN", { month: "long", year: "numeric" }).format(
    new Date(Number(y), Number(mo) - 1, 1)
  );
}

/** Extract Sandbox year/month from wizard period ``YYYY-MM-01``. */
function yearMonthFromPeriod(iso: string | null | undefined): { year: string; month: string } | null {
  if (!iso) return null;
  const [y, mo] = iso.slice(0, 10).split("-");
  if (!y || !mo) return null;
  return { year: y, month: mo };
}

function initialUiStep(run: ImportWizardRun | null): number {
  if (!run) return 1;
  if (isTerminalWizardStatus(run.status)) return 1;
  if (run.status === "pending" || run.status === "processing") return 4;
  if (run.status === "error") return 4;
  if (run.status === "pr_uploaded") {
    if (run.column_mapping && run.column_mapping.length > 0) return 4;
    return 3;
  }
  if (run.status === "gstr_uploaded") {
    if (run.current_step >= 2) return 3;
    return 2;
  }
  if (run.status === "draft") return 2;
  return 1;
}

function putWithProgress(
  url: string,
  file: File,
  hashHex: string,
  contentType: string,
  onProgress: (pct: number) => void
): Promise<void> {
  return new Promise((resolve, reject) => {
    const xhr = new XMLHttpRequest();
    xhr.open("PUT", url);
    xhr.setRequestHeader("Content-Type", contentType);
    xhr.setRequestHeader("X-File-Hash", hashHex);
    xhr.upload.onprogress = (ev) => {
      if (ev.lengthComputable) onProgress(Math.round((ev.loaded / ev.total) * 100));
    };
    xhr.onload = () => {
      if (xhr.status >= 200 && xhr.status < 300) resolve();
      else reject(new Error(`Upload failed (${xhr.status})`));
    };
    xhr.onerror = () => reject(new Error("Network error"));
    xhr.send(file);
  });
}

async function withRetries<T>(fn: () => Promise<T>, attempts = 3, delayMs = 2000): Promise<T> {
  let last: unknown;
  for (let i = 0; i < attempts; i++) {
    try {
      return await fn();
    } catch (e) {
      last = e;
      if (i < attempts - 1) await new Promise((r) => setTimeout(r, delayMs));
    }
  }
  throw last;
}

function extractErrorMessage(error: unknown, fallback: string): string {
  const e = error as { message?: unknown; detail?: unknown };
  if (typeof e?.message === "string" && e.message) return e.message;
  if (typeof e?.detail === "string" && e.detail) return e.detail;
  if (e?.detail && typeof e.detail === "object") {
    const detailMessage = (e.detail as { message?: unknown }).message;
    if (typeof detailMessage === "string" && detailMessage) return detailMessage;
    return JSON.stringify(e.detail);
  }
  if (typeof error === "string" && error) return error;
  if (error != null) {
    try {
      return JSON.stringify(error);
    } catch {
      /* ignore */
    }
  }
  return fallback;
}

function StepIndicator({ step }: { step: number }) {
  const labels = ["Select Period", "GSTR-2B", "Purchase Register", "Start"];
  return (
    <div className="mb-8 flex flex-wrap items-center gap-2">
      {labels.map((lb, i) => {
        const n = i + 1;
        const active = n === step;
        const done = n < step;
        return (
          <div key={lb} className="flex items-center gap-2">
            <div
              className={`flex h-8 w-8 items-center justify-center rounded-full text-sm font-semibold ${
                done
                  ? "bg-[var(--success)] text-white"
                  : active
                    ? "bg-[var(--ink)] text-white"
                    : "bg-[var(--border)] text-[var(--text-secondary)]"
              }`}
            >
              {done ? "✓" : n}
            </div>
            <span
              className={`text-sm ${active ? "font-semibold text-[var(--text-primary)]" : "text-[var(--text-secondary)]"}`}
            >
              {lb}
            </span>
            {i < labels.length - 1 ? (
              <span className="mx-1 text-[var(--text-secondary)]">→</span>
            ) : null}
          </div>
        );
      })}
    </div>
  );
}

export default function NewReconcileWizardPage() {
  const params = useParams();
  const router = useRouter();
  const searchParams = useSearchParams();
  const clientId = params?.client_id as string;

  /** `null` = auth still resolving; `string` = JWT; `false` = not signed in */
  const [token, setToken] = useState<string | null | false>(null);
  const [run, setRun] = useState<ImportWizardRun | null>(null);
  const [uiStep, setUiStep] = useState(1);
  const [period, setPeriod] = useState<string>("");
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  const [incompleteNotice, setIncompleteNotice] = useState<ImportWizardRun | null>(null);
  const [completedForPeriod, setCompletedForPeriod] = useState(false);

  const [gstrFile, setGstrFile] = useState<File | null>(null);
  const [changeGstrFile, setChangeGstrFile] = useState(false);
  const [gstrProgress, setGstrProgress] = useState(0);
  const [gstrUploadFailed, setGstrUploadFailed] = useState(false);
  const [sanityChecks, setSanityChecks] = useState<SanityCheckItem[] | null>(null);
  const [sanityBusy, setSanityBusy] = useState(false);
  const [prParseWarning, setPrParseWarning] = useState<string | null>(null);

  /** GSTN auto-fetch (Step 2) — only when client has a live GSTN session. */
  const [clientRow, setClientRow] = useState<ClientGstin | null>(null);
  const [showManualGstrUpload, setShowManualGstrUpload] = useState(false);
  const [gstnFetchBusy, setGstnFetchBusy] = useState(false);
  const [gstnFetchError, setGstnFetchError] = useState<string | null>(null);
  const [gstnFetchSummary, setGstnFetchSummary] = useState<string | null>(null);
  const [gstnZeroData, setGstnZeroData] = useState(false);
  /** Selected return period for GSTR-2B auto-fetch (Step 2). Defaults to wizard period if not set. */
  const [fetchMonth, setFetchMonth] = useState<string>("");
  const [fetchYear, setFetchYear] = useState<string>("");

  const [prFile, setPrFile] = useState<File | null>(null);
  const [prProgress, setPrProgress] = useState(0);
  const [prUploadFailed, setPrUploadFailed] = useState(false);
  /** Optional GSTR-3B claim period for Rule 37(3) interest (YYYY-MM-01). Empty = unset. */
  const [itcClaimedPeriod, setItcClaimedPeriod] = useState<string>("");
  const [detectBusy, setDetectBusy] = useState(false);
  const [preDetectBusy, setPreDetectBusy] = useState(false);
  const [allHeaders, setAllHeaders] = useState<string[]>([]);
  const [mappingLocal, setMappingLocal] = useState<ColumnMappingRow[] | null>(null);
  /** header → target_field for the pre-upload mapping UI */
  const [headerToTarget, setHeaderToTarget] = useState<
    Record<string, ImportTargetField | "">
  >({});
  const [savedMappingCovers, setSavedMappingCovers] = useState(false);
  const [schemaOk, setSchemaOk] = useState(false);
  const [mappingSaveError, setMappingSaveError] = useState<string | null>(null);
  const [confirmSavedMapping, setConfirmSavedMapping] = useState(false);
  const [sampleValues, setSampleValues] = useState<Record<string, string[]>>({});
  const [registerTypeDetection, setRegisterTypeDetection] =
    useState<RegisterTypeDetection | null>(null);
  const [registerTypeOverride, setRegisterTypeOverride] = useState<
    "purchase" | "sales" | null
  >(null);

  const [startBusy, setStartBusy] = useState(false);
  const [start409, setStart409] = useState<string | null>(null);
  const [creatingRun, setCreatingRun] = useState(false);
  const [showCancelConfirm, setShowCancelConfirm] = useState(false);
  const [zeroRecordConfirmed, setZeroRecordConfirmed] = useState(false);
  const [checkingRunStatus, setCheckingRunStatus] = useState(false);

  const [poll, setPoll] = useState<{ pct: number; message: string; status: string } | null>(null);
  const [pollSlow, setPollSlow] = useState(false);
  const pollStartRef = useRef<number | null>(null);

  /**
   * True when server-side detect-columns returned high confidence on all
   * required + tax fields with no low-confidence rows. Controls whether the
   * post-upload mapping table collapses to a compact confirmed summary.
   * This is a render-only flag — mappingLocal, requiredOk, taxOk, lowOk, and
   * canGoToStep4 are completely unaffected by its value.
   */
  const [mappingAutoConfirmed, setMappingAutoConfirmed] = useState(false);
  /** When true, always show the full post-upload table even if mappingAutoConfirmed. */
  const [showFullMappingTable, setShowFullMappingTable] = useState(false);

  const monthChoices = useMemo(() => pastMonthOptions(), []);

  const refreshRun = useCallback(
    async (rid: string, t: string) => {
      const r = await importWizardApi.getRun(t, rid);
      setRun(r);
      return r;
    },
    []
  );

  useEffect(() => subscribeAccessToken(setToken), []);

  useEffect(() => {
    if (typeof token !== "string" || !clientId) return;
    let cancelled = false;
    (async () => {
      try {
        const c = await clientsApi.get(token, clientId);
        if (!cancelled) {
          setClientRow(c);
          // Default to auto-fetch UI when GSTN is connected; otherwise keep manual-only.
          if (!isGstnConnected(c)) setShowManualGstrUpload(true);
        }
      } catch {
        if (!cancelled) setClientRow(null);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [token, clientId]);

  useEffect(() => {
    if (typeof token !== "string" || !clientId) return;
    let cancelled = false;
    (async () => {
      const supabase = createClient();
      const qRunId = searchParams.get("run_id");
      if (qRunId) {
        try {
          const r = await importWizardApi.getRun(token, qRunId);
          if (r.client_id !== clientId) {
            setErr("This run does not belong to this client.");
            return;
          }
          // If run already completed, navigate straight to results.
          if (r.status === "complete") {
            if (!cancelled) {
              router.replace(`/reconcile/runs/${qRunId}/results`);
            }
            return;
          }
          // Cancelled/error runs cannot accept uploads — drop the dead
          // run_id so Continue creates/resumes an active draft instead of 409s.
          if (isTerminalWizardStatus(r.status)) {
            if (!cancelled) {
              setRun(null);
              setUiStep(1);
              router.replace(`/reconcile/${clientId}/new`);
            }
            return;
          }
          if (!cancelled) {
            setRun(r);
            setUiStep(initialUiStep(r));
            if (r.column_mapping?.length) {
              setMappingLocal(r.column_mapping);
              setAllHeaders((r.pr_column_headers as string[] | null) ?? []);
            }
            if (r.sanity_check_results) setSanityChecks(r.sanity_check_results);
          }
        } catch {
          if (!cancelled) setErr("Could not load run.");
        }
        return;
      }

      const { data: active } = await (
        supabase as unknown as {
          from: (table: string) => ReturnType<typeof supabase.from>;
        }
      )
        .from("reconciliation_import_runs")
        .select("*")
        .eq("client_id", clientId)
        .in("status", [...ACTIVE_STATUSES])
        .maybeSingle();

      if (cancelled) return;
      if (active?.id) {
        setIncompleteNotice(active as ImportWizardRun);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [token, clientId, searchParams, router]);

  useEffect(() => {
    if (!run?.id) return;
    if (run.sanity_check_results?.length) setSanityChecks(run.sanity_check_results);
    if (run.column_mapping?.length) {
      setMappingLocal(run.column_mapping);
      const h = run.pr_column_headers;
      if (h && Array.isArray(h)) setAllHeaders(h as string[]);
    }
    setItcClaimedPeriod(
      run.itc_claimed_period ? String(run.itc_claimed_period).slice(0, 10) : ""
    );
  }, [run?.id]);

  useEffect(() => {
    if (typeof token !== "string" || !clientId || !period) return;
    let cancelled = false;
    (async () => {
      const supabase = createClient();
      const { data } = await (
        supabase as unknown as {
          from: (table: string) => ReturnType<typeof supabase.from>;
        }
      )
        .from("reconciliation_import_runs")
        .select("id")
        .eq("client_id", clientId)
        .eq("period", period)
        .eq("status", "complete")
        .maybeSingle();
      if (!cancelled) setCompletedForPeriod(!!data?.id);
    })();
    return () => {
      cancelled = true;
    };
  }, [token, clientId, period]);

  const onResume = async () => {
    if (typeof token !== "string" || !incompleteNotice) return;
    setErr(null);
    const r = await refreshRun(incompleteNotice.id, token);
    setIncompleteNotice(null);
    setRun(r);
    setUiStep(initialUiStep(r));
    router.replace(`/reconcile/${clientId}/new?run_id=${r.id}`);
    if (r.sanity_check_results) setSanityChecks(r.sanity_check_results);
    if (r.column_mapping?.length) {
      setMappingLocal(r.column_mapping);
      setAllHeaders((r.pr_column_headers as string[] | null) ?? []);
    }
  };

  const onStartFresh = async () => {
    if (typeof token !== "string" || !incompleteNotice) return;
    setErr(null);
    setBusy(true);
    try {
      await importWizardApi.cancel(token, incompleteNotice.id);
      setIncompleteNotice(null);
    } catch (e) {
      const ae = e as ApiError;
      setErr(ae.detail ?? "Could not cancel existing run.");
    } finally {
      setBusy(false);
    }
  };

  const onConfirmPeriod = async () => {
    if (typeof token !== "string") return;
    if (!period) {
      setErr("Select a period.");
      return;
    }
    setErr(null);
    setCreatingRun(true);
    try {
      // eslint-disable-next-line no-console -- debug: verify JWT sent on Continue
      const r = await importWizardApi.createRun(token, { client_id: clientId, period });
      setRun(r);
      Analytics.runStarted(period, "manual_upload");
      setUiStep(2);
      router.replace(`/reconcile/${clientId}/new?run_id=${r.id}`);
    } catch (e) {
      const ae = e as ApiError;
      setErr(ae.detail ?? "Could not create run.");
    } finally {
      setCreatingRun(false);
    }
  };

  const runId = run?.id ?? null;

  const runSanityWithRetry = async (activeRun?: ImportWizardRun) => {
    const currentRun = activeRun ?? run;
    const currentRunId = currentRun?.id ?? runId;
    if (typeof token !== "string" || !currentRunId) return;
    // Guard: only call if the run is in gstr_uploaded status — calling on a
    // "draft" run returns 409 and sets a confusing generic error banner.
    if (currentRun?.status !== "gstr_uploaded") return;
    setSanityBusy(true);
    setErr(null);
    try {
      const res = await withRetries(
        () => importWizardApi.sanityCheckGstr2b(token, currentRunId),
        3,
        1500
      );
      setSanityChecks(res.checks);
      await refreshRun(currentRunId, token);
    } catch (e) {
      const ae = e as ApiError;
      setErr(ae.detail ?? "Sanity check failed.");
    } finally {
      setSanityBusy(false);
    }
  };

  /** Shared R2 upload + sanity path used by both manual picker and GSTN auto-fetch. */
  const uploadGstrFile = async (file: File): Promise<boolean> => {
    if (typeof token !== "string" || !runId) return false;
    setErr(null);
    setGstrUploadFailed(false);
    const lower = file.name.toLowerCase();
    const isJson = lower.endsWith(".json");
    const isExcel = lower.endsWith(".xlsx") || lower.endsWith(".xls");
    if (!isJson && !isExcel) {
      setErr("File must be a .json, .xlsx, or .xls export.");
      return false;
    }
    if (file.size > MAX_UPLOAD) {
      setErr("File must be under 20 MB.");
      return false;
    }
    let uploadFile = file;
    let contentType = file.type || "application/octet-stream";
    if (isJson) {
      const text = await file.text();
      try {
        JSON.parse(text);
      } catch {
        setErr("This file is not valid JSON. Export again from the GST portal.");
        return false;
      }
      uploadFile = new File([text], file.name, { type: "application/json" });
      contentType = "application/json";
    } else if (lower.endsWith(".xlsx")) {
      contentType =
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet";
    } else {
      contentType = "application/vnd.ms-excel";
    }
    const hash = await sha256Hex(uploadFile);
    setBusy(true);
    setGstrProgress(0);
    try {
      const su = await importWizardApi.signedUrl(token, {
        type: "gstr2b",
        run_id: runId,
        file_name: uploadFile.name,
        content_type: contentType,
      });
      await withRetries(
        () =>
          putWithProgress(
            su.upload_url,
            uploadFile,
            hash,
            su.headers["Content-Type"] ?? contentType,
            setGstrProgress
          ),
        3,
        2000
      );
      const updated = await importWizardApi.gstr2bUploadComplete(token, runId, {
        r2_key: su.key,
        file_name: uploadFile.name,
        file_size: uploadFile.size,
        file_hash: hash,
      });

      // gstr2bUploadComplete returns a partial {sanity_check_results:[...]} object
      // (not a full ImportWizardRun) when the GSTIN in the file doesn't match the
      // client GSTIN. In that case the run stays "draft" in the DB and calling
      // runSanityWithRetry() would 409. Detect the early-exit by checking for the
      // absence of a run "status" field and surface the checks directly.
      const asRun = updated as { status?: string; sanity_check_results?: SanityCheckItem[] };
      if (!asRun.status && asRun.sanity_check_results?.length) {
        setSanityChecks(asRun.sanity_check_results);
      } else {
        setRun(updated);
        await runSanityWithRetry(updated);
        setGstrFile(null);
        setChangeGstrFile(false);
      }
      return true;
    } catch (e) {
      setGstrUploadFailed(true);
      setErr(
        extractErrorMessage(
          e,
          "Upload failed. Check your connection and try again."
        )
      );
      return false;
    } finally {
      setBusy(false);
    }
  };

  const onGstrUpload = async () => {
    if (!gstrFile) return;
    await uploadGstrFile(gstrFile);
  };

  const onGstnAutoFetch = async () => {
    if (typeof token !== "string" || !runId) return;
    const ym = {
      year: effectiveFetchYear,
      month: effectiveFetchMonth,
      ret_period: effectiveRetPeriod,
    };
    setGstnFetchBusy(true);
    setGstnFetchError(null);
    setGstnFetchSummary(null);
    setGstnZeroData(false);
    setErr(null);
    try {
      const result = await gstnApi.fetchGstr2b(token, clientId, ym);
      const payload = result.upload_payload;
      if (!payload || typeof payload !== "object") {
        throw {
          detail: "Fetch succeeded but no uploadable GSTR-2B payload was returned.",
          status: 502,
        };
      }
      const total = Number(result.total_parsed ?? 0);
      const fileName = `gstr2b_${ym.year}_${ym.month}_autofetch.json`;
      const file = new File([JSON.stringify(payload)], fileName, {
        type: "application/json",
      });
      setGstrFile(file);

      const uploaded = await uploadGstrFile(file);
      if (!uploaded) {
        setShowManualGstrUpload(true);
        return;
      }
      // Clear local file so the "Uploaded: …" summary shows (same as manual path).
      setGstrFile(null);
      if (total === 0) {
        setGstnZeroData(true);
        setGstnFetchSummary(null);
      } else {
        setGstnZeroData(false);
        setGstnFetchSummary(
          `Fetched ${total.toLocaleString("en-IN")} invoice${total === 1 ? "" : "s"} from GSTR-2B for ${effectiveFetchPeriodLabel} (Period ${effectiveRetPeriod})`
        );
      }
      // Background IMS prefetch for UX only — worker overlays status at match time.
      void gstnApi
        .fetchIms(token, clientId, ym)
        .then((ims) => {
          const pending = Number(ims.pending_action_count ?? 0);
          const mapSize = Number(ims.status_map_size ?? 0);
          setGstnFetchSummary((prev) => {
            const base =
              prev ??
              (total === 0
                ? `GSTR-2B fetched (0 invoices for ${effectiveFetchPeriodLabel})`
                : `Fetched ${total.toLocaleString("en-IN")} invoice${total === 1 ? "" : "s"} from GSTR-2B for ${effectiveFetchPeriodLabel}`);
            return `${base} · IMS: ${mapSize.toLocaleString("en-IN")} mapped (${pending.toLocaleString("en-IN")} pending action)`;
          });
        })
        .catch(() => {
          /* soft-fail — reconcile still works without IMS */
        });
    } catch (e) {
      const ae = e as ApiError;
      setGstnFetchError(ae.detail ?? "Couldn't fetch GSTR-2B automatically.");
      setShowManualGstrUpload(true);
    } finally {
      setGstnFetchBusy(false);
    }
  };

  const onPrFileSelected = async (file: File | null) => {
    setPrFile(file);
    setPrUploadFailed(false);
    setMappingSaveError(null);
    setConfirmSavedMapping(false);
    setHeaderToTarget({});
    setAllHeaders([]);
    setSavedMappingCovers(false);
    setSchemaOk(false);
    setRegisterTypeDetection(null);
    setRegisterTypeOverride(null);
    setMappingAutoConfirmed(false);
    setShowFullMappingTable(false);
    if (!file || typeof token !== "string" || !clientId) return;
    const ext = file.name.split(".").pop()?.toLowerCase() ?? "";
    if (!["csv", "xlsx", "xls"].includes(ext)) {
      setErr("Use .csv, .xlsx, or .xls only.");
      return;
    }
    if (file.size > MAX_UPLOAD) {
      setErr("File must be under 20 MB.");
      return;
    }
    setPreDetectBusy(true);
    setErr(null);
    try {
      const res = await prUploadApi.detectColumns(token, file, clientId);
      setAllHeaders(res.headers);
      setSchemaOk(!!res.schema_ok);
      setSavedMappingCovers(!!res.saved_mapping_covers);
      setSampleValues(res.sample_values || {});
      if (res.register_type_detection) {
        setRegisterTypeDetection({
          ...res.register_type_detection,
          pipeline_mismatch:
            res.register_type_detection.register_type === "sales" &&
            (res.register_type_detection.confidence === "high" ||
              res.register_type_detection.confidence === "medium"),
        });
      }
      const next: Record<string, ImportTargetField | ""> = {};
      for (const h of res.headers) next[h] = "";
      if (res.saved_mapping_covers && res.saved_mapping?.length) {
        for (const m of res.saved_mapping) {
          if (res.headers.includes(m.source_column_name)) {
            next[m.source_column_name] = m.target_field;
          }
        }
        setConfirmSavedMapping(true);
      } else if (res.saved_mapping?.length) {
        for (const m of res.saved_mapping) {
          if (res.headers.includes(m.source_column_name)) {
            next[m.source_column_name] = m.target_field;
          }
        }
      } else if (res.suggested_mapping?.length) {
        for (const m of res.suggested_mapping) {
          if (res.headers.includes(m.source_column_name)) {
            next[m.source_column_name] = m.target_field;
          }
        }
      }
      setHeaderToTarget(next);
    } catch (e) {
      const ae = e as ApiError;
      setErr(ae.detail ?? "Could not read file columns.");
    } finally {
      setPreDetectBusy(false);
    }
  };

  const onRegisterTypeOverride = (type: "purchase" | "sales") => {
    if (type === "sales") {
      const href = clientId
        ? `/reconcile/gstr1/new?client_gstin_id=${encodeURIComponent(clientId)}`
        : "/reconcile/gstr1/new";
      router.push(href);
      return;
    }
    setRegisterTypeOverride("purchase");
  };

  const buildMappingItems = (): ClientImportMappingItem[] | null => {
    const items: ClientImportMappingItem[] = [];
    const used = new Set<ImportTargetField>();
    for (const [header, target] of Object.entries(headerToTarget)) {
      if (!target) continue;
      if (used.has(target)) {
        setMappingSaveError(`Each field can only be mapped once (${MAPPING_FIELD_LABELS[target] ?? target}).`);
        return null;
      }
      used.add(target);
      items.push({ source_column_name: header, target_field: target });
    }
    if (!requiredTargetsMapped(headerToTarget)) {
      setMappingSaveError("Map GSTIN, invoice number, invoice date, and taxable value.");
      return null;
    }
    if (!isTaxMapped(headerToTarget)) {
      setMappingSaveError("Map at least one tax field (CGST, SGST, IGST, or Cess).");
      return null;
    }
    setMappingSaveError(null);
    return items;
  };

  const onPrUpload = async () => {
    if (typeof token !== "string" || !runId || !prFile || !clientId) return;
    setErr(null);
    setMappingSaveError(null);
    setPrUploadFailed(false);
    const ext = prFile.name.split(".").pop()?.toLowerCase() ?? "";
    if (!["csv", "xlsx", "xls"].includes(ext)) {
      setErr("Use .csv, .xlsx, or .xls only.");
      return;
    }
    if (prFile.size > MAX_UPLOAD) {
      setErr("File must be under 20 MB.");
      return;
    }

    const needsManualMapping = !schemaOk && !savedMappingCovers;
    const usingSaved = savedMappingCovers && confirmSavedMapping;
    if (needsManualMapping || (savedMappingCovers && !confirmSavedMapping && !schemaOk)) {
      const items = buildMappingItems();
      if (!items) return;
      try {
        await prUploadApi.saveMapping(token, clientId, items);
      } catch (e) {
        const ae = e as ApiError;
        setMappingSaveError(ae.detail ?? "Could not save column mapping.");
        return;
      }
    } else if (usingSaved) {
      // Saved mapping already covers — keep it; no rewrite needed.
    } else if (!schemaOk) {
      const items = buildMappingItems();
      if (!items) return;
      try {
        await prUploadApi.saveMapping(token, clientId, items);
      } catch (e) {
        const ae = e as ApiError;
        setMappingSaveError(ae.detail ?? "Could not save column mapping.");
        return;
      }
    }

    const hash = await sha256Hex(prFile);
    setBusy(true);
    setPrProgress(0);
    try {
      const ct = prFile.type || (ext === "csv" ? "text/csv" : "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet");
      const su = await importWizardApi.signedUrl(token, {
        type: "purchase_register",
        run_id: runId,
        file_name: prFile.name,
        content_type: ct,
      });
      await withRetries(
        () => putWithProgress(su.upload_url, prFile, hash, su.headers["Content-Type"] ?? ct, setPrProgress),
        3,
        2000
      );
      const updated = await importWizardApi.prUploadComplete(token, runId, {
        r2_key: su.key,
        file_name: prFile.name,
        file_size: prFile.size,
        file_hash: hash,
        ...(itcClaimedPeriod ? { itc_claimed_period: itcClaimedPeriod } : {}),
      });
      setRun(updated);
      Analytics.runCompleted({ period, matched: 0, mismatched: 0, pending: 0, duration_s: 0 });
      await runDetectWithRetry();
    } catch (e) {
      setPrUploadFailed(true);
      setErr(
        extractErrorMessage(
          e,
          "Upload failed. Check your connection and try again."
        )
      );
    } finally {
      setBusy(false);
    }
  };

  const runDetectWithRetry = async () => {
    if (typeof token !== "string" || !runId) return;
    setDetectBusy(true);
    setErr(null);
    try {
      const res = await withRetries(() => importWizardApi.detectColumns(token, runId), 3, 1500);
      setMappingLocal(res.columns);
      setAllHeaders(res.all_headers);
      setPrParseWarning(res.pr_parse_warning?.trim() || null);
      if (res.sanity_check_results?.length) {
        setSanityChecks(res.sanity_check_results);
      }
      if (res.saved_mapping_covers) {
        setSavedMappingCovers(true);
        setConfirmSavedMapping(true);
      }
      if (typeof res.schema_ok === "boolean") setSchemaOk(res.schema_ok);
      // Option A — auto-confirm check (render-only, does not affect canGoToStep4).
      // Collapse the post-upload mapping table to a compact summary when the server
      // agrees with what the CA already confirmed pre-upload: all required fields
      // at high confidence, at least one tax field at high confidence, and no row
      // has low confidence (low requires a manual checkbox and should not be hidden).
      // Medium or below on ANY field keeps the full table visible.
      {
        const cols = res.columns;
        const reqAllHigh = REQUIRED_MAPPING_FIELDS.every((f) => {
          const row = cols.find((r) => r.standard_field === f);
          return !!row?.detected_column && row.confidence === "high";
        });
        const taxHigh = TAX_MAPPING_FIELDS.some((f) => {
          const row = cols.find((r) => r.standard_field === f);
          return !!row?.detected_column && row.confidence === "high";
        });
        const noLowAnywhere = cols.every((r) => r.confidence !== "low");
        setMappingAutoConfirmed(reqAllHigh && taxHigh && noLowAnywhere);
        setShowFullMappingTable(false);
      }
      const r = await refreshRun(runId, token);
      setRun(r);
      if (r.sanity_check_results) setSanityChecks(r.sanity_check_results);
    } catch (e) {
      const ae = e as ApiError;
      setErr(ae.detail ?? "Column detection failed.");
    } finally {
      setDetectBusy(false);
    }
  };

  const persistMapping = async (next: ColumnMappingRow[]) => {
    if (typeof token !== "string" || !runId) return;
    setMappingLocal(next);
    await importWizardApi.patchRun(token, runId, { column_mapping: next });
    const r = await refreshRun(runId, token);
    setRun(r);
  };

  const onMappingChange = async (field: string, header: string) => {
    if (!mappingLocal || !runId) return;
    const row = mappingLocal.find((m) => m.standard_field === field);
    const next: ColumnMappingRow[] = mappingLocal.map((m) =>
      m.standard_field === field
        ? {
            ...m,
            detected_column: header || null,
            confidence: "high",
            confirmed: true,
            sample_values: m.sample_values,
          }
        : m
    );
    await persistMapping(next);
    const updated = next.find((m) => m.standard_field === field);
    if (row && typeof token === "string") {
      await importWizardApi.confirmMapping(token, runId, {
        field,
        detected_column: updated?.detected_column ?? null,
        confidence: updated?.confidence ?? "high",
        method: "manual",
      });
    }
  };

  const onMappingConfirmLow = async (field: string) => {
    if (!mappingLocal) return;
    const row = mappingLocal.find((m) => m.standard_field === field);
    const next = mappingLocal.map((m) =>
      m.standard_field === field ? { ...m, confirmed: true } : m
    );
    await persistMapping(next);
    if (row && typeof token === "string" && runId) {
      await importWizardApi.confirmMapping(token, runId, {
        field,
        detected_column: row.detected_column,
        confidence: row.confidence,
        method: "auto",
      });
    }
  };

  const onDismissWarning = async (c: SanityCheckItem) => {
    if (typeof token !== "string" || !runId) return;
    await importWizardApi.acknowledgeWarning(token, runId, {
      check_id: c.id,
      check_label: c.label,
    });
    const r = await refreshRun(runId, token);
    setRun(r);
    if (r.sanity_check_results) setSanityChecks(r.sanity_check_results);
  };

  const checksDisplayed = sanityChecks ?? run?.sanity_check_results ?? [];
  const sanityErrors = checksDisplayed.filter(
    (c) => String(c.status).toLowerCase() === "error"
  );
  const sanityWarnings = checksDisplayed.filter(
    (c) => String(c.status).toLowerCase() === "warning"
  );
  // High-risk warnings declare requires_acknowledgment on the check itself
  // (multi_sheet_combine, missing_invoice_number, GSTR 0-parsed, …).
  const blockingAckWarnings = checksDisplayed.filter(
    (c) =>
      !!c.requires_acknowledgment &&
      String(c.status).toLowerCase() === "warning"
  );
  const highRiskWarningsOk = !blockingAckWarnings.some((c) => !c.acknowledged);

  const requiredOk =
    !!mappingLocal?.length &&
    REQUIRED_MAPPING_FIELDS.every((field) => {
      const row = mappingLocal.find((m) => m.standard_field === field);
      return !!row?.detected_column && row.confidence !== "not_found";
    });
  const taxOk =
    !!mappingLocal?.length &&
    (
      TAX_MAPPING_FIELDS.some((field) => {
        const row = mappingLocal.find((m) => m.standard_field === field);
        return !!row?.detected_column && row.confidence !== "not_found";
      }) ||
      (() => {
        const row = mappingLocal.find((m) => m.standard_field === "total_tax");
        return !!row?.detected_column && row.confidence !== "not_found";
      })()
    );
  const lowOk =
    !mappingLocal ||
    mappingLocal.every((m) => {
      if (isOptionalMappingField(m.standard_field)) {
        if (!m.detected_column || m.confidence === "not_found") return true;
      }
      if (
        (TAX_MAPPING_FIELDS as readonly string[]).includes(m.standard_field) &&
        (!m.detected_column || m.confidence === "not_found")
      ) {
        return true;
      }
      if (!m.detected_column) return false;
      if (m.confidence !== "low") return true;
      return m.confirmed;
    });

  const canGoToStep3 =
    sanityErrors.length === 0 && highRiskWarningsOk && !!checksDisplayed.length;
  const canGoToStep4 =
    requiredOk && taxOk && lowOk && !!mappingLocal?.length && highRiskWarningsOk;

  const step3BlockingWarnings = blockingAckWarnings.filter((c) =>
    ["multi_sheet_combine", "missing_invoice_number"].includes(String(c.id))
  );

  const gstnConnected = isGstnConnected(clientRow);
  const step2PeriodIso = (run?.period || period || "").slice(0, 10);
  const step2PeriodLabel = step2PeriodIso ? periodLabel(step2PeriodIso) : "selected period";

  const defaultYm = useMemo(() => {
    const fromIso = yearMonthFromPeriod(step2PeriodIso);
    if (fromIso) return fromIso;
    const d = new Date();
    return {
      year: String(d.getFullYear()),
      month: String(d.getMonth() + 1).padStart(2, "0"),
    };
  }, [step2PeriodIso]);

  const effectiveFetchMonth = fetchMonth || defaultYm.month;
  const effectiveFetchYear = fetchYear || defaultYm.year;
  const effectiveRetPeriod = `${effectiveFetchMonth}${effectiveFetchYear}`;

  const effectiveFetchPeriodLabel = useMemo(() => {
    const yNum = Number(effectiveFetchYear);
    const mNum = Number(effectiveFetchMonth);
    if (Number.isFinite(yNum) && Number.isFinite(mNum) && mNum >= 1 && mNum <= 12) {
      return new Intl.DateTimeFormat("en-IN", { month: "long", year: "numeric" }).format(
        new Date(yNum, mNum - 1, 1)
      );
    }
    return `${effectiveFetchMonth}/${effectiveFetchYear}`;
  }, [effectiveFetchYear, effectiveFetchMonth]);

  const yearOptions = useMemo(() => {
    const currentYear = new Date().getFullYear();
    const list: string[] = [];
    for (let yr = currentYear + 1; yr >= currentYear - 3; yr--) {
      list.push(String(yr));
    }
    return list;
  }, []);

  const quickPeriodPresets = useMemo(() => {
    const presets: { label: string; month: string; year: string }[] = [];
    const d = new Date();
    let y = d.getFullYear();
    let m = d.getMonth();
    const fmt = new Intl.DateTimeFormat("en-IN", { month: "short", year: "numeric" });
    for (let i = 0; i < 4; i++) {
      presets.push({
        label: fmt.format(new Date(y, m, 1)),
        month: String(m + 1).padStart(2, "0"),
        year: String(y),
      });
      m -= 1;
      if (m < 0) {
        m = 11;
        y -= 1;
      }
    }
    return presets;
  }, []);

  const preUploadMappingComplete =
    requiredTargetsMapped(headerToTarget) && isTaxMapped(headerToTarget);
  const registerTypeBlocksUpload =
    !!registerTypeDetection &&
    registerTypeOverride !== "purchase" &&
    (registerTypeDetection.requires_manual_choice ||
      registerTypeDetection.register_type === "ambiguous" ||
      (!!registerTypeDetection.pipeline_mismatch &&
        registerTypeDetection.register_type === "sales"));
  const canConfirmAndUpload =
    !!prFile &&
    !busy &&
    !preDetectBusy &&
    allHeaders.length > 0 &&
    !registerTypeBlocksUpload &&
    (savedMappingCovers
      ? confirmSavedMapping || preUploadMappingComplete
      : schemaOk || preUploadMappingComplete);

  const onBack = async () => {
    if (uiStep <= 1) return;
    const next = uiStep - 1;
    setUiStep(next);
    if (typeof token === "string" && runId && run) {
      const newCompleted = Math.max(1, (run.current_step ?? 1) - 1);
      try {
        await importWizardApi.patchRun(token, runId, { current_step: newCompleted });
        await refreshRun(runId, token);
      } catch {
        /* non-fatal */
      }
    }
  };

  const onStart = async () => {
    if (typeof token !== "string" || !runId) return;
    setStart409(null);
    setStartBusy(true);
    setErr(null);
    // Show the "processing" spinner immediately while the blocking request runs.
    setPoll({ pct: 0, message: "Starting…", status: "processing" });
    // Transition local run state to "processing" so the spinner screen renders
    // before the long-running fetch resolves.
    setRun((prev) => prev ? { ...prev, status: "processing", progress_pct: 0, status_message: "Starting…" } : prev);
    try {
      // This call blocks until the engine finishes (or errors). Railway
      // keep-alive is 300s; asyncio.to_thread() keeps the event loop unblocked.
      await importWizardApi.start(token, runId);
      const r = await refreshRun(runId, token);
      setRun(r);
      // If the engine finished synchronously, redirect immediately.
      if (r.status === "complete") {
        router.push(`/reconcile/runs/${runId}/results`);
        return;
      }
      // Error state: let the error UI show.
      if (r.status === "error") {
        setPoll(null);
        return;
      }
      // Fallback: still processing (shouldn't normally happen) — start polling.
      pollStartRef.current = Date.now();
      setPollSlow(false);
      setPoll({ pct: r.progress_pct ?? 0, message: r.status_message ?? "Processing…", status: r.status });
    } catch (err: unknown) {
      const e = err as {
        response?: { status?: number; data?: { detail?: unknown } };
        status?: number;
        detail?: unknown;
        message?: string;
      };
      const status = e?.response?.status ?? e?.status;

      // Revert optimistic "processing" UI — the server never advanced the run.
      try {
        const r = await refreshRun(runId, token);
        setRun(r);
      } catch {
        setRun((prev) =>
          prev
            ? {
                ...prev,
                status: "pr_uploaded",
                progress_pct: 0,
                status_message: null,
              }
            : prev
        );
      }
      setPoll(null);

      // ── Recovery check ────────────────────────────────────────────────────────
      // importWizardApi.start() is a blocking HTTP call (~300 s Railway timeout).
      // If the client-side network drops or the fetch times out, this catch block
      // fires even if the engine already completed successfully on the server.
      // Poll once to find the true server-side state before showing any error.
      // Do NOT remove: prevents "succeeded but looks failed" and silent
      // duplicate-run submissions when the CA hits Retry on a finished run.
      try {
        const recovery = await importWizardApi.pollStatus(token, runId);

        if (recovery.status === "complete") {
          // Engine finished while we were disconnected — redirect silently,
          // same as the normal success path. No error is shown.
          router.push(`/reconcile/runs/${runId}/results`);
          return;
        }

        if (recovery.status === "processing" || recovery.status === "pending") {
          // Engine still running — re-attach the polling loop by flipping run
          // state to "processing". The useEffect keyed on run?.status picks it up.
          setRun((prev) =>
            prev ? { ...prev, status: "processing" as const } : prev
          );
          pollStartRef.current = Date.now();
          setPollSlow(false);
          setPoll({
            pct: recovery.progress_pct,
            message:
              "We lost connection, but your reconciliation may still be running. Checking status…",
            status: "processing",
          });
          return;
        }

        // "error" / "failed" / "cancelled" — fall through to existing error UI below.
      } catch {
        // pollStatus itself failed (e.g. 404, network still down) — fall through to
        // existing error UI below.
      }
      // ── End recovery check ────────────────────────────────────────────────────

      if (status === 402) {
        setErr("No runs remaining on your current plan. Please upgrade to continue.");
        return;
      }
      if (status === 429) {
        setErr("Too many requests. Please wait a moment and try again.");
        return;
      }

      const rawDetail = e?.response?.data?.detail ?? e?.detail;
      const message =
        (typeof rawDetail === "string" ? rawDetail : null) ||
        (rawDetail &&
        typeof rawDetail === "object" &&
        typeof (rawDetail as { message?: unknown }).message === "string"
          ? (rawDetail as { message: string }).message
          : null) ||
        e?.message ||
        "Something went wrong. Please try again.";

      if (status === 409) setStart409(message);
      else setErr(message);
    } finally {
      setStartBusy(false);
    }
  };


  const onCancelRun = async () => {
    if (typeof token !== "string" || !runId) return;
    setBusy(true);
    try {
      await importWizardApi.cancel(token, runId);
      router.push(`/clients/${clientId}`);
    } catch (e) {
      const ae = e as ApiError;
      setErr(ae.detail ?? "Cancel failed.");
    } finally {
      setBusy(false);
    }
  };

  const onRetryError = async () => {
    if (typeof token !== "string" || !runId) return;
    setErr(null);
    try {
      const r = await importWizardApi.retry(token, runId);
      setRun(r);
      setStart409(null);
    } catch (e) {
      setErr(extractErrorMessage(e, "Retry failed."));
    }
  };

  const checkRunStatus = async () => {
    if (typeof token !== "string" || !runId) return;
    setCheckingRunStatus(true);
    try {
      const st = await importWizardApi.pollStatus(token, runId);
      const r = await refreshRun(runId, token);
      setRun(r);
      if (st.status === "complete" || r.status === "complete") {
        router.push(`/reconcile/runs/${runId}/results`);
        return;
      }
      if (st.status === "processing" || st.status === "pending") {
        setErr(null);
        setRun((prev) => (prev ? { ...prev, status: "processing" as const } : prev));
        pollStartRef.current = Date.now();
        setPollSlow(false);
        setPoll({
          pct: st.progress_pct ?? 0,
          message: st.message || "Reconciliation is running on the server…",
          status: "processing",
        });
        return;
      }
      if (st.status === "error" || r.status === "error") {
        setErr(
          extractErrorMessage(
            r.error_detail || st.message,
            "Processing failed on the server."
          )
        );
        return;
      }
      if (r.status === "pr_uploaded") {
        setErr(
          "Reconciliation has not started yet on the server. You can click 'Start reconciliation' below."
        );
      }
    } catch {
      setErr(
        "Could not reach server to verify run status. Please check your internet connection."
      );
    } finally {
      setCheckingRunStatus(false);
    }
  };

  useEffect(() => {
    if (typeof token !== "string" || !runId) return;
    if (run?.status !== "pending" && run?.status !== "processing") return;

    let cancelled = false;
    let pollTimer: ReturnType<typeof setTimeout> | undefined;
    const t0 = pollStartRef.current ?? Date.now();
    pollStartRef.current = t0;
    const POLL_INTERVAL_MS = 3000;

    const scheduleNext = () => {
      if (cancelled) return;
      pollTimer = setTimeout(() => {
        void tick();
      }, POLL_INTERVAL_MS);
    };

    const tick = async () => {
      if (cancelled) return;
      try {
        const s = await importWizardApi.pollStatus(token, runId);
        if (cancelled) return;
        setPoll({ pct: s.progress_pct, message: s.message, status: s.status });
        if (s.status === "complete") {
          router.push(`/reconcile/runs/${runId}/results`);
          return;
        }
        if (s.status === "error" || s.status === "failed") {
          await refreshRun(runId, token);
          return;
        }
        if (s.status !== "pending" && s.status !== "processing") {
          const r = await refreshRun(runId, token);
          if (!cancelled) setRun(r);
          return;
        }
        if (Date.now() - t0 > 5 * 60 * 1000) setPollSlow(true);
        scheduleNext();
      } catch {
        /* ignore transient poll errors, keep polling */
        scheduleNext();
      }
    };

    void tick();

    return () => {
      cancelled = true;
      if (pollTimer != null) clearTimeout(pollTimer);
    };
  }, [token, runId, run?.status, router, refreshRun]);

  if (token === null) {
    return (
      <div className="dashboard-card flex min-h-[40vh] flex-col items-center justify-center gap-4 p-8 text-[var(--text-secondary)]">
        <svg
          className="h-8 w-8 animate-spin text-[var(--ink)]"
          xmlns="http://www.w3.org/2000/svg"
          fill="none"
          viewBox="0 0 24 24"
          aria-hidden
        >
          <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
          <path
            className="opacity-75"
            fill="currentColor"
            d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z"
          />
        </svg>
        <p className="text-sm">Checking authentication…</p>
      </div>
    );
  }

  if (token === false) {
    return (
      <div className="dashboard-card p-8 text-[var(--text-secondary)]">
        Sign in to continue.
      </div>
    );
  }

  if (run?.status === "pending" || run?.status === "processing") {
    const pct = poll?.pct ?? run.progress_pct ?? 0;
    const msg = poll?.message || run.status_message || "Processing…";
    return (
      <div className="mx-auto max-w-lg dashboard-card space-y-6 p-8">
        <h1 className="text-2xl font-semibold tracking-tight text-[var(--ink)]">Reconciliation in progress</h1>
        <p className="text-[var(--text-primary)]">{msg}</p>
        <div className="h-3 w-full overflow-hidden rounded-full bg-[var(--border)]">
          <div
            className="h-full bg-[var(--ink)] transition-all"
            style={{ width: `${Math.min(100, pct)}%` }}
          />
        </div>
        <p className="font-mono text-sm text-[var(--text-secondary)]">{pct}%</p>
        {err ? (
          <div className="space-y-3 rounded-lg border border-[var(--danger)]/30 bg-[var(--danger)]/5 p-4 text-sm text-[var(--text-primary)]">
            <p>{err}</p>
            {err.includes("upgrade") || err.includes("plan") ? (
              <Link
                href="/billing"
                className="inline-flex rounded-full bg-[var(--ink)] px-4 py-2 text-sm font-semibold text-white transition-opacity hover:opacity-90"
              >
                Go to Billing
              </Link>
            ) : null}
          </div>
        ) : null}
        {pollSlow ? (
          <p className="text-sm text-[var(--text-secondary)]">
            This is taking longer than expected. Please keep this page open — reconciliation is still running.
          </p>
        ) : null}
        <div className="flex flex-wrap gap-3">
          {showCancelConfirm ? (
            <div className="w-full rounded-xl border border-[var(--warning)] bg-amber-50 p-4 text-sm text-amber-950">
              <p className="font-medium">Cancel this reconciliation? This cannot be undone.</p>
              <div className="mt-3 flex gap-3">
                <button
                  type="button"
                  disabled={busy}
                  onClick={onCancelRun}
                  className="rounded-full bg-red-600 px-4 py-2 text-sm font-semibold text-white transition-opacity disabled:opacity-50 hover:opacity-90"
                >
                  {busy ? "Cancelling…" : "Cancel run"}
                </button>
                <button
                  type="button"
                  disabled={busy}
                  onClick={() => setShowCancelConfirm(false)}
                  className="rounded-full border border-[var(--border)] px-4 py-2 text-sm font-medium text-amber-950 hover:bg-amber-100"
                >
                  Keep running
                </button>
              </div>
            </div>
          ) : (
            <button
              type="button"
              onClick={() => setShowCancelConfirm(true)}
              className="rounded-full border border-[var(--border)] px-4 py-2 text-sm font-medium text-[var(--text-primary)] hover:bg-[var(--bg)]"
            >
              Cancel run
            </button>
          )}
          <Link
            href="/dashboard"
            className="rounded-full bg-[var(--ink)] px-4 py-2 text-sm font-semibold text-white transition-opacity hover:opacity-90"
          >
            Back to Dashboard
          </Link>
        </div>
      </div>
    );
  }

  return (
    <div className="mx-auto max-w-4xl space-y-6">
      <div className="flex flex-wrap items-center justify-between gap-4">
        <div>
          <h1 className="text-2xl font-semibold tracking-tight text-[var(--ink)]">New reconciliation</h1>
          <p className="text-sm text-[var(--text-secondary)]">
            Client: <span className="font-mono">{clientId}</span>
          </p>
        </div>
        <Link
          href={`/clients/${clientId}`}
          className="text-sm font-medium text-[var(--ink)] hover:underline"
        >
          ← Back to client
        </Link>
      </div>

      <StepIndicator step={uiStep} />

      {incompleteNotice ? (
        <div className="rounded-xl border border-[var(--warning)] bg-amber-50 p-4 text-sm text-amber-950">
          <p className="font-medium">
            You have an incomplete reconciliation for {periodLabel(incompleteNotice.period)}. Resume it?
          </p>
          <div className="mt-3 flex gap-3">
            <button
              type="button"
              onClick={onResume}
              className="rounded-full bg-[var(--ink)] px-4 py-2 text-sm font-semibold text-white transition-opacity hover:opacity-90"
            >
              Resume
            </button>
            <button
              type="button"
              onClick={onStartFresh}
              disabled={busy}
              className="rounded-full border border-[var(--border)] px-4 py-2 text-sm font-medium"
            >
              Start fresh
            </button>
          </div>
        </div>
      ) : null}

      {err ? (
        <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-3 rounded-lg border border-[var(--danger)] bg-red-50 px-4 py-3 text-sm text-red-900">
          <p className="flex-1">{err}</p>
          {runId ? (
            <button
              type="button"
              onClick={() => void checkRunStatus()}
              disabled={checkingRunStatus}
              className="shrink-0 inline-flex items-center gap-1.5 rounded-lg border border-red-300 bg-white px-3 py-1.5 text-xs font-semibold text-red-800 shadow-sm hover:bg-red-50 disabled:opacity-50"
            >
              {checkingRunStatus ? (
                <>
                  <Loader2 className="h-3.5 w-3.5 animate-spin" />
                  Checking…
                </>
              ) : (
                "Check Run Status"
              )}
            </button>
          ) : null}
        </div>
      ) : null}

      {uiStep === 1 ? (
        <div className="dashboard-card space-y-4 p-6">
          <h2 className="text-lg font-semibold tracking-tight text-[var(--ink)]">Select period</h2>
          <label className="block text-sm text-[var(--text-secondary)]">
            Month
            <select
              value={period}
              onChange={(e) => setPeriod(e.target.value)}
              className="mt-1 w-full max-w-xs rounded-lg border border-[var(--border)] bg-white px-3 py-2 text-[var(--text-primary)]"
            >
              <option value="">Choose…</option>
              {monthChoices.map((m) => (
                <option key={m.value} value={m.value}>
                  {m.label}
                </option>
              ))}
            </select>
          </label>
          {completedForPeriod && period ? (
            <p className="text-sm text-[var(--text-secondary)]">
              A completed reconciliation already exists for this period. Starting a new one will be a separate run.
            </p>
          ) : null}
          <button
            type="button"
            disabled={!period || creatingRun}
            onClick={onConfirmPeriod}
            className="inline-flex items-center justify-center gap-2 rounded-full bg-[var(--ink)] px-5 py-2.5 text-sm font-semibold text-white transition-all disabled:cursor-not-allowed disabled:opacity-50 hover:opacity-90"
          >
            {creatingRun ? (
              <>
                <Loader2 className="h-4 w-4 animate-spin text-white" />
                <span>Creating…</span>
              </>
            ) : (
              <span>Continue</span>
            )}
          </button>
        </div>
      ) : null}

      {uiStep === 2 && runId ? (
        <div className="dashboard-card space-y-4 p-6">
          <div className="flex items-center justify-between">
            <h2 className="text-lg font-semibold tracking-tight text-[var(--ink)]">
              {gstnConnected && !showManualGstrUpload && !run?.gstr2b_file_name
                ? "GSTR-2B"
                : "Upload GSTR-2B"}
            </h2>
            <button type="button" onClick={onBack} className="text-sm text-[var(--ink)] hover:underline">
              Back
            </button>
          </div>

          {gstnConnected && !showManualGstrUpload && !run?.gstr2b_file_name ? (
            <div className="space-y-4">
              <p className="text-sm text-[var(--text-secondary)]">
                GSTN is connected for this client. Select a return period below to auto-fetch official GSTR-2B returns directly from the GST portal.
              </p>

              {/* Month and Year Selector */}
              <div className="rounded-xl border border-[var(--border)] bg-gray-50/70 p-4 space-y-3">
                <div className="flex flex-wrap items-center justify-between gap-2">
                  <span className="text-xs font-semibold uppercase tracking-wider text-[var(--text-secondary)]">
                    Return Period (ret_period)
                  </span>
                  <span className="inline-flex items-center gap-1.5 rounded-md bg-[var(--ink)]/5 px-2.5 py-1 font-mono text-xs font-medium text-[var(--ink)]">
                    <span className="h-1.5 w-1.5 rounded-full bg-emerald-500" />
                    GSTN Code: <strong className="font-mono">{effectiveRetPeriod}</strong>
                  </span>
                </div>

                <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
                  <div>
                    <label htmlFor="fetch-month-select" className="block text-xs font-medium text-[var(--text-secondary)] mb-1">
                      Return Month
                    </label>
                    <select
                      id="fetch-month-select"
                      value={effectiveFetchMonth}
                      onChange={(e) => setFetchMonth(e.target.value)}
                      disabled={gstnFetchBusy}
                      className="w-full rounded-lg border border-[var(--border)] bg-white px-3 py-2 text-sm text-[var(--text-primary)] focus:outline-none focus:ring-2 focus:ring-[var(--ink)]/20"
                    >
                      {MONTH_NAMES.map((name, idx) => {
                        const val = String(idx + 1).padStart(2, "0");
                        return (
                          <option key={val} value={val}>
                            {name} ({val})
                          </option>
                        );
                      })}
                    </select>
                  </div>

                  <div>
                    <label htmlFor="fetch-year-select" className="block text-xs font-medium text-[var(--text-secondary)] mb-1">
                      Return Year
                    </label>
                    <select
                      id="fetch-year-select"
                      value={effectiveFetchYear}
                      onChange={(e) => setFetchYear(e.target.value)}
                      disabled={gstnFetchBusy}
                      className="w-full rounded-lg border border-[var(--border)] bg-white px-3 py-2 text-sm text-[var(--text-primary)] focus:outline-none focus:ring-2 focus:ring-[var(--ink)]/20"
                    >
                      {yearOptions.map((yr) => (
                        <option key={yr} value={yr}>
                          {yr}
                        </option>
                      ))}
                    </select>
                  </div>
                </div>

                {/* Quick Period Presets */}
                <div className="pt-1 flex flex-wrap items-center gap-1.5">
                  <span className="text-xs text-[var(--text-secondary)] mr-1">Quick Select:</span>
                  {quickPeriodPresets.map((preset) => {
                    const isSelected =
                      preset.month === effectiveFetchMonth && preset.year === effectiveFetchYear;
                    return (
                      <button
                        key={preset.label}
                        type="button"
                        onClick={() => {
                          setFetchMonth(preset.month);
                          setFetchYear(preset.year);
                        }}
                        disabled={gstnFetchBusy}
                        className={`rounded-full px-2.5 py-1 text-xs font-medium transition-colors ${
                          isSelected
                            ? "bg-[var(--ink)] text-white"
                            : "bg-white border border-[var(--border)] text-[var(--text-secondary)] hover:text-[var(--text-primary)] hover:border-gray-400"
                        }`}
                      >
                        {preset.label}
                      </button>
                    );
                  })}
                </div>
              </div>

              <div className="flex flex-wrap items-center gap-3">
                <button
                  type="button"
                  disabled={gstnFetchBusy || busy}
                  onClick={onGstnAutoFetch}
                  className="rounded-full bg-[var(--ink)] px-5 py-2.5 text-sm font-semibold text-white transition-opacity disabled:opacity-50 hover:opacity-90 shadow-sm"
                >
                  {gstnFetchBusy
                    ? `Fetching GSTR-2B for ${effectiveFetchPeriodLabel}…`
                    : `Fetch GSTR-2B for ${effectiveFetchPeriodLabel} (${effectiveRetPeriod})`}
                </button>
                <button
                  type="button"
                  onClick={() => setShowManualGstrUpload(true)}
                  className="text-sm text-[var(--text-secondary)] underline-offset-2 hover:text-[var(--ink)] hover:underline"
                >
                  Upload manually instead
                </button>
              </div>
            </div>
          ) : null}

          {gstnFetchSummary ? (
            <div className="rounded-lg border border-[var(--success)] bg-emerald-50 p-3 text-sm text-emerald-950">
              {gstnFetchSummary}
            </div>
          ) : null}

          {gstnZeroData ? (
            <div className="space-y-3 rounded-lg border border-amber-300 bg-amber-50 p-4 text-sm text-amber-950">
              <p>
                No GSTR-2B data found for this period. This could mean no purchases were filed, or
                the data isn&apos;t published yet.
              </p>
              <div className="flex flex-wrap gap-2">
                <button
                  type="button"
                  onClick={() => setUiStep(1)}
                  className="rounded-full border border-amber-400 bg-white px-3 py-1.5 text-sm font-medium"
                >
                  Try a different period
                </button>
                <button
                  type="button"
                  onClick={() => setUiStep(3)}
                  className="rounded-full bg-[var(--ink)] px-3 py-1.5 text-sm font-semibold text-white transition-opacity hover:opacity-90"
                >
                  Continue anyway
                </button>
              </div>
            </div>
          ) : null}

          {gstnFetchError ? (
            <div className="space-y-3 rounded-lg border border-[var(--danger)] bg-red-50 p-4 text-sm text-red-900">
              <p>
                Couldn&apos;t fetch GSTR-2B automatically.{" "}
                <span className="font-medium">{gstnFetchError}</span>
              </p>
              <div className="flex flex-wrap items-center gap-3">
                <Link
                  href={`/clients/${clientId}?return_to=${encodeURIComponent(`/reconcile/${clientId}/new${runId ? `?run_id=${runId}` : ""}`)}`}
                  className="rounded-full border border-red-300 bg-white px-3 py-1.5 text-sm font-medium text-red-900 hover:bg-red-100"
                >
                  Reconnect GSTN
                </Link>
                <span className="text-xs text-red-700">
                  (Your wizard progress is saved and you can resume anytime)
                </span>
                <button
                  type="button"
                  onClick={() => {
                    setShowManualGstrUpload(true);
                    setGstnFetchError(null);
                  }}
                  className="text-sm font-medium text-[var(--ink)] underline-offset-2 hover:underline"
                >
                  Upload manually instead
                </button>
              </div>
            </div>
          ) : null}

          {(!gstnConnected || showManualGstrUpload || !!run?.gstr2b_file_name) && (
            <>
              {run?.gstr2b_file_name && !gstrFile && sanityErrors.length === 0 && !changeGstrFile ? (
                <div className="flex items-center justify-between gap-2 rounded-xl border border-gray-200 bg-gray-50/50 px-4 py-3">
                  <p className="text-sm text-[var(--text-secondary)]">
                    Uploaded: <strong className="text-[var(--ink)]">{run.gstr2b_file_name}</strong> ({formatBytes(run.gstr2b_file_size)})
                  </p>
                  <button
                    type="button"
                    onClick={() => {
                      setChangeGstrFile(true);
                      setShowManualGstrUpload(true);
                    }}
                    className="text-sm font-medium text-[var(--ink)] hover:underline"
                  >
                    Change file
                  </button>
                </div>
              ) : (
                <>
                  {run?.gstr2b_file_name && sanityErrors.length > 0 && !gstrFile ? (
                    <p className="text-sm text-[var(--text-secondary)]">
                      Previous upload: <strong>{run.gstr2b_file_name}</strong> (
                      {formatBytes(run.gstr2b_file_size)}). Choose a different file and upload again.
                    </p>
                  ) : null}
                  {gstnConnected && showManualGstrUpload ? (
                    <div className="flex items-center justify-between gap-2">
                      <h3 className="text-sm font-medium text-[var(--text-primary)]">
                        Upload GSTR-2B
                      </h3>
                      <button
                        type="button"
                        onClick={() => {
                          setShowManualGstrUpload(false);
                          setChangeGstrFile(false);
                          setGstnFetchError(null);
                        }}
                        className="text-sm text-[var(--ink)] hover:underline"
                      >
                        Back to auto-fetch
                      </button>
                    </div>
                  ) : changeGstrFile ? (
                    <div className="flex items-center justify-between gap-2">
                      <h3 className="text-sm font-medium text-[var(--text-primary)]">
                        Upload GSTR-2B
                      </h3>
                      <button
                        type="button"
                        onClick={() => setChangeGstrFile(false)}
                        className="text-sm text-[var(--text-secondary)] hover:underline"
                      >
                        Cancel
                      </button>
                    </div>
                  ) : null}
                  <FileDropzone
                    accept=".json,.xlsx,.xls,application/json,application/vnd.ms-excel,application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
                    allowedExtensions={[".json", ".xlsx", ".xls"]}
                    selectedFile={gstrFile}
                    onFileSelect={setGstrFile}
                    progress={gstrProgress}
                    title="Drop GSTR-2B file here, or click to browse"
                    subtitle="Official GSTN JSON or portal Excel (.json, .xlsx, .xls)"
                    hintTags={["GSTN JSON", "Portal Excel", "Max 25 MB"]}
                    disabled={busy || gstnFetchBusy}
                  />
                  {gstrFile && gstrFile.size < 10000 ? (
                    <p className="text-xs text-amber-800 bg-amber-50 p-2.5 rounded-xl border border-amber-200">
                      ⚠️ Expected GSTN export is usually larger than 10 KB; please confirm this is not the sample copy.
                    </p>
                  ) : null}
                  <button
                    type="button"
                    disabled={!gstrFile || busy || gstnFetchBusy}
                    onClick={onGstrUpload}
                    className="rounded-full bg-[var(--ink)] px-4 py-2 text-sm font-semibold text-white transition-opacity disabled:opacity-50 hover:opacity-90"
                  >
                    Upload &amp; verify
                  </button>
                  {gstrUploadFailed ? (
                    <button
                      type="button"
                      onClick={onGstrUpload}
                      className="ml-2 rounded-full border px-4 py-2 text-sm"
                    >
                      Retry upload
                    </button>
                  ) : null}
                </>
              )}
            </>
          )}

          {sanityBusy ? (
            <p className="text-sm text-[var(--text-secondary)]">Running sanity checks…</p>
          ) : null}

          {checksDisplayed.length ? (
            <div className="space-y-3">
              {sanityErrors.length ? (
                <div className="rounded-lg border border-[var(--danger)] bg-red-50 p-3 text-sm text-red-900">
                  <p className="font-semibold">Cannot proceed — fix the following and re-upload:</p>
                  <ul className="mt-1.5 space-y-1">
                    {sanityErrors.map((c, i) => {
                      // Support both API shapes:
                      //  • sanity-check endpoint  → { id, label, detail }
                      //  • upload-complete GSTIN  → { name, status, message }
                      const name = (c as { name?: string }).name ?? c.label;
                      const msg  = (c as { message?: string }).message ?? c.detail;
                      return (
                        <li key={c.id ?? i} className="flex gap-1.5">
                          <span className="shrink-0 font-bold" aria-hidden>✕</span>
                          <span>
                            <span className="font-semibold">{name}</span>
                            {msg ? <> &mdash; {msg}</> : null}
                          </span>
                        </li>
                      );
                    })}
                  </ul>
                </div>
              ) : null}
              {sanityErrors.length === 0 &&
              blockingAckWarnings.some((w) => !w.acknowledged) ? (
                <div className="rounded-lg border border-[var(--warning)] bg-amber-50 p-3 text-sm text-amber-950">
                  Acknowledge high-risk warnings before continuing.
                </div>
              ) : sanityErrors.length === 0 &&
                sanityWarnings.some((w) => !w.acknowledged) ? (
                <div className="rounded-lg border border-[var(--warning)] bg-amber-50 p-3 text-sm text-amber-950">
                  Review warnings before continuing.
                </div>
              ) : null}
              <ul className="space-y-2">
                {checksDisplayed.map((c, idx) => {
                  const st = String(c.status).toLowerCase();
                  const isError = st === "error";
                  const isWarning = st === "warning";
                  const title =
                    "name" in c && typeof (c as { name?: string }).name === "string"
                      ? (c as { name: string }).name
                      : c.label;
                  const messageText =
                    "message" in c && typeof (c as { message?: string }).message === "string"
                      ? (c as { message: string }).message
                      : c.detail;
                  return (
                    <li
                      key={c.id || `sanity-${idx}-${title}`}
                      className={
                        isError
                          ? "flex flex-wrap items-start gap-2 rounded-lg border-2 border-red-500 bg-red-50 p-4 text-sm shadow-sm"
                          : isWarning
                            ? "flex flex-wrap items-start gap-2 rounded-lg border border-amber-300 bg-amber-50/90 p-3 text-sm"
                            : "flex flex-wrap items-start gap-2 rounded-lg border border-[var(--border)] p-3 text-sm"
                      }
                    >
                      {st === "pass" ? (
                        <span className="text-[var(--success)]">✓</span>
                      ) : isWarning ? (
                        <span className="text-[var(--warning)]">⚠</span>
                      ) : (
                        <span className="font-semibold text-red-700">✕</span>
                      )}
                      <div className="flex-1">
                        <div
                          className={
                            isError
                              ? "font-semibold text-red-950"
                              : isWarning
                                ? "font-medium text-amber-950"
                                : "font-medium"
                          }
                        >
                          {title}
                        </div>
                        {messageText ? (
                          <div
                            className={
                              isError
                                ? "mt-1 text-sm font-medium text-red-900"
                                : "text-[var(--text-secondary)]"
                            }
                          >
                            {messageText}
                          </div>
                        ) : null}
                        {c.affected_records?.length ? (
                          <ul className="mt-1 font-mono text-xs text-[var(--text-secondary)]">
                            {c.affected_records.slice(0, 20).map((a, i) => (
                              <li key={i}>
                                {a.gstin} — {a.invoice_number}
                              </li>
                            ))}
                          </ul>
                        ) : null}
                        {isWarning ? (
                          <button
                            type="button"
                            disabled={!!c.acknowledged}
                            onClick={() => onDismissWarning(c)}
                            className="mt-2 rounded border px-2 py-1 text-xs font-medium disabled:opacity-50"
                          >
                            {c.acknowledged
                              ? c.requires_acknowledgment
                                ? "Acknowledged"
                                : "Dismissed"
                              : c.requires_acknowledgment
                                ? "I understand — continue"
                                : "Dismiss"}
                          </button>
                        ) : null}
                      </div>
                    </li>
                  );
                })}
              </ul>
              {sanityErrors.length ? (
                <button
                  type="button"
                  onClick={() => {
                    setGstrFile(null);
                    setSanityChecks(null);
                    setGstnFetchSummary(null);
                    setGstnZeroData(false);
                    if (gstnConnected) setShowManualGstrUpload(false);
                  }}
                  className="text-sm font-medium text-[var(--ink)]"
                >
                  Re-upload GSTR-2B
                </button>
              ) : null}
            </div>
          ) : null}

          <p className="text-xs text-[var(--text-secondary)]">
            Your files are processed on Indian servers, not shared with third parties, and deleted within 24 hours of run
            completion.
          </p>

          <button
            type="button"
            disabled={!canGoToStep3}
            onClick={() => setUiStep(3)}
            className="rounded-full bg-[var(--ink)] px-4 py-2 text-sm font-semibold text-white transition-opacity hover:opacity-90 disabled:cursor-not-allowed disabled:bg-gray-400 disabled:text-gray-100 disabled:opacity-90 disabled:hover:opacity-90"
          >
            Continue to purchase register
          </button>
        </div>
      ) : null}

      {uiStep === 3 && runId ? (
        <div className="dashboard-card space-y-4 p-6">
          <div className="flex items-center justify-between">
            <h2 className="text-lg font-semibold tracking-tight text-[var(--ink)]">Upload purchase register</h2>
            <button type="button" onClick={onBack} className="text-sm text-[var(--ink)] hover:underline">
              Back
            </button>
          </div>

          <div className="space-y-1.5 rounded-lg border border-[var(--border)] bg-[#FAFAFA] p-3">
            <label
              htmlFor="itc-claimed-period"
              className="block text-sm font-medium text-[var(--ink)]"
            >
              ITC claimed period{" "}
              <span className="font-normal text-[var(--text-secondary)]">(optional)</span>
            </label>
            <p className="text-[12px] leading-relaxed text-[var(--text-secondary)]">
              GSTR-3B month when ITC for this purchase register was claimed. Used to estimate Rule 37
              interest from the following month&apos;s 20th (GSTR-3B due date), not from the invoice
              date. Leave blank if unknown — interest will be shown as a lower bound from the 180-day
              deadline.
            </p>
            <select
              id="itc-claimed-period"
              value={itcClaimedPeriod}
              onChange={(e) => {
                const v = e.target.value;
                setItcClaimedPeriod(v);
                if (typeof token === "string" && runId) {
                  void importWizardApi
                    .patchRun(token, runId, { itc_claimed_period: v })
                    .then(setRun)
                    .catch(() => {
                      /* non-blocking; value still sent on PR upload / continue */
                    });
                }
              }}
              className="mt-1 max-w-xs rounded border border-[var(--border)] bg-white px-2 py-1.5 text-sm"
            >
              <option value="">— not set —</option>
              {monthChoices.map((m) => (
                <option key={m.value} value={m.value}>
                  {m.label}
                </option>
              ))}
            </select>
          </div>

          {run?.pr_file_name && !prFile ? (
            <p className="text-sm text-[var(--text-secondary)]">
              Uploaded: <strong>{run.pr_file_name}</strong> ({formatBytes(run.pr_file_size)})
            </p>
          ) : (
            <>
              <FileDropzone
                accept=".csv,.xlsx,.xls"
                allowedExtensions={[".xlsx", ".xls", ".csv"]}
                selectedFile={prFile}
                onFileSelect={(f) => void onPrFileSelected(f)}
                progress={prProgress}
                title="Drop Purchase Register here, or click to browse"
                subtitle="Tally, Busy, Marg, or custom Excel/CSV registers"
                hintTags={["TallyPrime", "Busy", "Excel .xlsx", "CSV", "Max 25 MB"]}
                disabled={busy}
              />
              <div className="rounded-xl border border-brand-dim bg-brand-dim/30 p-3 text-xs text-gray-800">
                <span className="font-semibold text-brand">✨ Low-effort upload:</span> We auto-detect Tally, Busy, and Excel layouts automatically — no template or formatting needed!
              </div>
              <p className="text-[12px] text-[var(--text-secondary)]">
                Accepts Tally Purchase Register exports (Excel/CSV) and custom accounting books. (Optional for GSTR-2B compliance views; upload for full GSTR ↔ PR matching).
              </p>
              {preDetectBusy ? (
                <p className="text-sm text-[var(--text-secondary)]">Reading columns…</p>
              ) : null}
              {registerTypeDetection ? (
                <RegisterTypeDetectionBanner
                  detection={registerTypeDetection}
                  expectedType="purchase"
                  clientId={clientId}
                  overridden={registerTypeOverride === "purchase"}
                  onOverride={onRegisterTypeOverride}
                  onClearOverride={() => setRegisterTypeOverride(null)}
                  busy={preDetectBusy}
                />
              ) : (
                <details className="rounded-lg border border-[var(--border)] bg-[#FAFAFA] px-3 py-2 text-[12px] text-gray-600">
                  <summary className="cursor-pointer font-medium text-[var(--ink)]">
                    How to export from Tally (Purchase Register)
                  </summary>
                  <p className="mt-2 leading-relaxed">
                    In TallyPrime: Gateway of Tally → Display More Reports → Statutory
                    Reports → GST → GSTR-2 / Purchase Register → set period → Alt+E
                    (Export) → Excel or CSV. In Tally ERP 9: Gateway of Tally → Display →
                    Statutory Reports → GST → GSTR-2 → Export. Include GSTIN and tax
                    columns in the export configuration.
                  </p>
                </details>
              )}

              {savedMappingCovers && allHeaders.length > 0 && !mappingLocal?.length ? (
                <div className="rounded-lg border border-emerald-200 bg-emerald-50 p-3 text-sm text-emerald-900">
                  Using saved mapping from last upload.
                  <div className="mt-3">
                    <button
                      type="button"
                      disabled={!canConfirmAndUpload}
                      onClick={onPrUpload}
                      className="rounded-full bg-[var(--ink)] px-4 py-2 text-sm font-semibold text-white transition-opacity disabled:opacity-50 hover:opacity-90"
                    >
                      Confirm &amp; Upload
                    </button>
                    <button
                      type="button"
                      onClick={() => {
                        setConfirmSavedMapping(false);
                        setSavedMappingCovers(false);
                      }}
                      className="ml-2 text-sm text-[var(--ink)] hover:underline"
                    >
                      Edit mapping
                    </button>
                  </div>
                </div>
              ) : null}

              {!savedMappingCovers && allHeaders.length > 0 && !mappingLocal?.length ? (
                <div className="space-y-3">
                  {!schemaOk ? (
                    <p className="text-sm text-[var(--text-secondary)]">
                      Map your file columns to ReconDesk fields. Required fields show a red asterisk;
                      at least one tax field is required.
                    </p>
                  ) : (
                    <p className="text-sm text-[var(--text-secondary)]">
                      Columns look standard. You can upload as-is, or adjust the mapping below.
                    </p>
                  )}
                  <div className="overflow-x-auto">
                    <table className="w-full min-w-[560px] border-collapse text-left text-sm">
                      <thead>
                        <tr className="border-b border-[var(--border)] text-[var(--text-secondary)]">
                          <th className="py-2 pr-3">Your file has:</th>
                          <th className="py-2 pr-3">Sample data:</th>
                          <th className="py-2 pr-3">Maps to:</th>
                        </tr>
                      </thead>
                      <tbody>
                        {allHeaders.map((header) => {
                          const selected = headerToTarget[header] ?? "";
                          const usedElsewhere = new Set(
                            Object.entries(headerToTarget)
                              .filter(([h, t]) => h !== header && t)
                              .map(([, t]) => t)
                          );
                          const samples = sampleValues[header] || [];
                          return (
                            <tr key={header} className="border-b border-[var(--border)]">
                              <td className="py-2 pr-3 font-mono text-xs text-[var(--text-primary)]">{header}</td>
                              <td className="py-2 pr-3 text-xs text-[var(--text-secondary)] max-w-[220px] truncate">
                                {samples.length > 0 ? (
                                  <span title={samples.join(" | ")} className="font-mono text-[11px] text-zinc-600">
                                    {samples.join(", ")}
                                  </span>
                                ) : (
                                  <span className="text-zinc-400 italic">none</span>
                                )}
                              </td>
                              <td className="py-2 pr-3">
                                <select
                                  value={selected}
                                  onChange={(e) => {
                                    const v = e.target.value as ImportTargetField | "";
                                    setHeaderToTarget((prev) => ({ ...prev, [header]: v }));
                                    setMappingSaveError(null);
                                  }}
                                  className="max-w-[220px] rounded border border-[var(--border)] bg-white px-2 py-1 text-xs"
                                >
                                  <option value="">— skip —</option>
                                  {IMPORT_TARGET_FIELDS.map((tf) => (
                                    <option
                                      key={tf}
                                      value={tf}
                                      disabled={usedElsewhere.has(tf) && selected !== tf}
                                    >
                                      {MAPPING_FIELD_LABELS[tf] ?? tf}
                                      {(REQUIRED_MAPPING_FIELDS as readonly string[]).includes(tf)
                                        ? " *"
                                        : ""}
                                    </option>
                                  ))}
                                </select>
                              </td>
                            </tr>
                          );
                        })}
                      </tbody>
                    </table>
                  </div>
                  <div className="flex flex-wrap gap-3 text-xs text-[var(--text-secondary)]">
                    {REQUIRED_MAPPING_FIELDS.map((f) => {
                      const mapped = Object.values(headerToTarget).includes(f);
                      return (
                        <span key={f} className={mapped ? "text-emerald-700" : "text-red-700"}>
                          {MAPPING_FIELD_LABELS[f]}
                          <span className="text-red-600">*</span>
                          {mapped ? " ✓" : ""}
                        </span>
                      );
                    })}
                    <span className={isTaxMapped(headerToTarget) ? "text-emerald-700" : "text-red-700"}>
                      Tax (CGST/SGST/IGST/Cess)*
                      {isTaxMapped(headerToTarget) ? " ✓" : ""}
                    </span>
                  </div>
                  {mappingSaveError ? (
                    <div className="rounded-lg border border-[var(--danger)] bg-red-50 p-3 text-sm text-red-900">
                      {mappingSaveError}
                    </div>
                  ) : null}
                  <button
                    type="button"
                    disabled={!canConfirmAndUpload}
                    onClick={onPrUpload}
                    className="rounded-full bg-[var(--ink)] px-4 py-2 text-sm font-semibold text-white transition-opacity disabled:opacity-50 hover:opacity-90"
                  >
                    {schemaOk ? "Upload & continue" : "Save mapping & upload"}
                  </button>
                </div>
              ) : null}

              {prUploadFailed ? (
                <button type="button" onClick={onPrUpload} className="rounded-full border px-4 py-2 text-sm">
                  Retry upload
                </button>
              ) : null}
            </>
          )}

          {detectBusy ? <p className="text-sm text-[var(--text-secondary)]">Detecting columns…</p> : null}

          {step3BlockingWarnings.map((w) => (
            <div
              key={w.id}
              className="space-y-2 rounded-lg border border-amber-300 bg-amber-50 p-3 text-sm text-amber-950"
            >
              <div className="font-medium">{w.label}</div>
              <p>{w.detail}</p>
              <button
                type="button"
                disabled={!!w.acknowledged}
                onClick={() => onDismissWarning(w)}
                className="rounded border border-amber-400 bg-white px-2 py-1 text-xs font-medium disabled:opacity-50"
              >
                {w.acknowledged ? "Acknowledged" : "I understand — continue"}
              </button>
            </div>
          ))}

          {prParseWarning &&
          !step3BlockingWarnings.some((w) => w.id === "missing_invoice_number") ? (
            <div className="rounded-lg border border-amber-300 bg-amber-50 p-3 text-sm text-amber-950">
              {prParseWarning}
            </div>
          ) : null}

          {!highRiskWarningsOk && step3BlockingWarnings.some((w) => !w.acknowledged) ? (
            <p className="text-sm text-amber-900">
              Acknowledge high-risk warnings before continuing.
            </p>
          ) : null}

          {!requiredOk && mappingLocal?.length ? (
            <div className="rounded-lg border border-[var(--danger)] bg-red-50 p-3 text-sm text-red-900">
              Required columns could not be detected. Assign them manually.
            </div>
          ) : null}
          {!taxOk && mappingLocal?.length && requiredOk ? (
            <div className="rounded-lg border border-[var(--danger)] bg-red-50 p-3 text-sm text-red-900">
              Map at least one tax field (CGST, SGST, IGST, Cess, or Total tax).
            </div>
          ) : null}

          {mappingLocal?.length ? (
            mappingAutoConfirmed && !showFullMappingTable ? (
              // Compact confirmed summary — all required + tax fields returned at high
              // confidence with no low-confidence rows. The CA already mapped columns
              // pre-upload; this just confirms the server agreed. canGoToStep4 is
              // still governed by requiredOk/taxOk/lowOk derived from mappingLocal.
              <div className="rounded-lg border border-emerald-200 bg-emerald-50 p-4 space-y-3">
                <div className="flex items-center gap-2 text-sm font-semibold text-emerald-800">
                  <span aria-hidden="true">✓</span> Mapping confirmed
                </div>
                <ul className="space-y-1.5">
                  {mappingLocal
                    .filter((row) => !!row.detected_column)
                    .map((row) => (
                      <li key={row.standard_field} className="flex items-baseline gap-2 text-sm">
                        <span className="w-36 shrink-0 text-xs font-medium text-[var(--text-secondary)]">
                          {MAPPING_FIELD_LABELS[row.standard_field] ?? row.standard_field}
                          {isOptionalMappingField(row.standard_field) ? (
                            <span className="ml-1 font-normal text-gray-400">(opt)</span>
                          ) : null}
                        </span>
                        <span className="text-xs text-[var(--text-secondary)]">→</span>
                        <span className="font-mono text-xs text-[var(--text-primary)]">
                          {row.detected_column}
                        </span>
                      </li>
                    ))}
                </ul>
                <button
                  type="button"
                  onClick={() => setShowFullMappingTable(true)}
                  className="text-xs text-[var(--ink)] underline-offset-2 hover:underline"
                >
                  Show full mapping table
                </button>
              </div>
            ) : (
              <div className="overflow-x-auto">
                {showFullMappingTable && mappingAutoConfirmed ? (
                  <div className="mb-3 flex items-center justify-between gap-4">
                    <p className="text-xs text-[var(--text-secondary)]">
                      Mapping was auto-confirmed — showing full table for review.
                    </p>
                    <button
                      type="button"
                      onClick={() => setShowFullMappingTable(false)}
                      className="shrink-0 text-xs text-[var(--ink)] underline-offset-2 hover:underline"
                    >
                      Back to summary
                    </button>
                  </div>
                ) : null}
                <table className="w-full min-w-[640px] border-collapse text-left text-sm">
                  <thead>
                    <tr className="border-b border-[var(--border)] text-[var(--text-secondary)]">
                      <th className="py-2 pr-3">Standard field</th>
                      <th className="py-2 pr-3">Detected column</th>
                      <th className="py-2 pr-3">Confidence</th>
                      <th className="py-2 pr-3">Sample values</th>
                      <th className="py-2 pr-3">Action</th>
                    </tr>
                  </thead>
                  <tbody>
                    {mappingLocal.map((row) => {
                      const optional = isOptionalMappingField(row.standard_field);
                      const notFound =
                        row.confidence === "not_found" || !row.detected_column;
                      const optionalMissing = optional && notFound;
                      const highlight =
                        optionalMissing
                          ? ""
                          : row.confidence === "low" || row.confidence === "not_found"
                            ? "bg-amber-50"
                            : "";
                      const badge = optionalMissing
                        ? "bg-gray-100 text-gray-600 dark:bg-gray-800 dark:text-gray-400"
                        : row.confidence === "high"
                          ? "bg-emerald-100 text-emerald-800"
                          : row.confidence === "medium"
                            ? "bg-amber-100 text-amber-900"
                            : "bg-red-100 text-red-800";
                      const fieldLabel =
                        MAPPING_FIELD_LABELS[row.standard_field] ?? row.standard_field;
                      return (
                        <tr key={row.standard_field} className={`border-b border-[var(--border)] ${highlight}`}>
                          <td className="py-2 pr-3 font-medium">
                            {fieldLabel}
                            {optional ? (
                              <span className="ml-1.5 text-xs font-normal text-gray-500 dark:text-gray-400">
                                (Optional)
                              </span>
                            ) : null}
                          </td>
                          <td
                            className={`py-2 pr-3 ${
                              optionalMissing ? "text-gray-500 dark:text-gray-400" : ""
                            }`}
                          >
                            {row.detected_column ??
                              (optionalMissing ? "Not found" : "—")}
                          </td>
                          <td className="py-2 pr-3">
                            <span className={`rounded px-2 py-0.5 text-xs font-medium capitalize ${badge}`}>
                              {row.confidence.replace("_", " ")}
                            </span>
                          </td>
                          <td className="py-2 pr-3 font-mono text-xs text-[var(--text-secondary)]">
                            {(row.sample_values ?? []).join(" · ") || "—"}
                          </td>
                          <td className="py-2 pr-3">
                            <select
                              value={row.detected_column ?? ""}
                              onChange={(e) => onMappingChange(row.standard_field, e.target.value)}
                              className="max-w-[180px] rounded border border-[var(--border)] bg-white px-2 py-1 text-xs"
                            >
                              <option value="">—</option>
                              {allHeaders.map((h) => (
                                <option key={h} value={h}>
                                  {h}
                                </option>
                              ))}
                            </select>
                            {row.confidence === "low" && row.detected_column ? (
                              <label className="mt-1 flex items-center gap-2 text-xs">
                                <input
                                  type="checkbox"
                                  checked={row.confirmed}
                                  onChange={() => {
                                    if (!row.confirmed) void onMappingConfirmLow(row.standard_field);
                                  }}
                                />
                                I confirm this mapping is correct
                              </label>
                            ) : null}
                          </td>
                        </tr>
                      );
                    })}
                  </tbody>
                </table>
              </div>
            )
          ) : null}

          <p className="text-xs text-[var(--text-secondary)]">
            Your files are processed on Indian servers, not shared with third parties, and deleted within 24 hours of run
            completion.
          </p>

          <button
            type="button"
            disabled={!canGoToStep4}
            onClick={() => {
              void (async () => {
                if (typeof token === "string" && clientId && mappingLocal?.length) {
                  const items: ClientImportMappingItem[] = [];
                  const used = new Set<string>();
                  for (const row of mappingLocal) {
                    const tf = row.standard_field as ImportTargetField;
                    if (!(IMPORT_TARGET_FIELDS as readonly string[]).includes(tf)) continue;
                    if (!row.detected_column) continue;
                    if (used.has(tf)) continue;
                    used.add(tf);
                    items.push({
                      source_column_name: row.detected_column,
                      target_field: tf,
                    });
                  }
                  const hasRequired = REQUIRED_MAPPING_FIELDS.every((f) =>
                    items.some((i) => i.target_field === f)
                  );
                  const hasTax = TAX_MAPPING_FIELDS.some((f) =>
                    items.some((i) => i.target_field === f)
                  );
                  if (hasRequired && hasTax) {
                    try {
                      await prUploadApi.saveMapping(token, clientId, items);
                    } catch {
                      /* non-fatal — run mapping still on the wizard run */
                    }
                  }
                }
                if (typeof token === "string" && runId) {
                  try {
                    const updated = await importWizardApi.patchRun(token, runId, {
                      itc_claimed_period: itcClaimedPeriod,
                    });
                    setRun(updated);
                  } catch {
                    /* non-fatal — value may already be saved on change / PR upload */
                  }
                }
                setUiStep(4);
              })();
            }}
            className="rounded-full bg-[var(--ink)] px-4 py-2 text-sm font-semibold text-white transition-opacity hover:opacity-90 disabled:opacity-50"
          >
            Continue to start
          </button>
        </div>
      ) : null}

      {uiStep === 4 && runId ? (
        <div className="dashboard-card space-y-4 p-6">
          <div className="flex items-center justify-between">
            <h2 className="text-lg font-semibold tracking-tight text-[var(--ink)]">Start reconciliation</h2>
            <button type="button" onClick={onBack} className="text-sm text-[var(--ink)] hover:underline">
              Back
            </button>
          </div>

          {run?.status === "error" ? (
            <div className="rounded-lg border border-[var(--danger)] bg-red-50 p-3 text-sm text-red-900">
              {extractErrorMessage(run.error_detail, "Processing failed.")}
              <div className="mt-2 flex flex-wrap items-center gap-2">
                <button
                  type="button"
                  onClick={onRetryError}
                  className="rounded-lg border border-[var(--border)] bg-white px-3 py-1 text-sm font-medium"
                >
                  Try again
                </button>
                <button
                  type="button"
                  onClick={() => void checkRunStatus()}
                  disabled={checkingRunStatus}
                  className="inline-flex items-center gap-1.5 rounded-lg border border-red-300 bg-white px-3 py-1 text-sm font-medium text-red-800 hover:bg-red-50 disabled:opacity-50"
                >
                  {checkingRunStatus ? (
                    <>
                      <Loader2 className="h-3.5 w-3.5 animate-spin" />
                      Checking status…
                    </>
                  ) : (
                    "Check Run Status"
                  )}
                </button>
              </div>
            </div>
          ) : null}

          <div className="rounded-lg border border-[var(--border)] bg-[var(--bg)] p-4 text-sm">
            <div>
              <span className="text-[var(--text-secondary)]">Period:</span>{" "}
              <strong>{run ? periodLabel(run.period) : "—"}</strong>
            </div>
            <div className="mt-2">
              <span className="text-[var(--text-secondary)]">GSTR-2B:</span>{" "}
              {run?.gstr2b_file_name ?? "—"} ({formatBytes(run?.gstr2b_file_size)}) —{" "}
              {run?.gstr2b_record_count ?? 0} records
            </div>
            <div className="mt-2">
              <span className="text-[var(--text-secondary)]">Purchase register:</span>{" "}
              {run?.pr_file_name ?? "—"} ({formatBytes(run?.pr_file_size)}) — {run?.pr_record_count ?? 0} records
            </div>
            {(run?.itc_claimed_period || itcClaimedPeriod) ? (
              <div className="mt-2">
                <span className="text-[var(--text-secondary)]">ITC claimed period:</span>{" "}
                <strong>
                  {periodLabel(run?.itc_claimed_period || itcClaimedPeriod)}
                </strong>
              </div>
            ) : null}
            <p className="mt-3 font-medium text-[var(--text-primary)]">
              {run?.gstr2b_record_count ?? 0} GSTR-2B records vs {run?.pr_record_count ?? 0} Purchase Register records
            </p>
          </div>

          {(() => {
            const hasZeroGstr2b = (run?.gstr2b_record_count ?? 0) === 0;
            const hasZeroPr = (run?.pr_record_count ?? 0) === 0;
            if (!hasZeroGstr2b && !hasZeroPr) return null;

            return (
              <div className="rounded-xl border border-amber-300 bg-amber-50/90 p-4 text-sm text-amber-950 space-y-2.5">
                <div className="flex items-start gap-2.5">
                  <span className="inline-block mt-0.5 text-base">⚠️</span>
                  <div className="space-y-1">
                    <p className="font-semibold text-amber-900">
                      {hasZeroGstr2b && hasZeroPr
                        ? "Zero Records in Both GSTR-2B and Purchase Register"
                        : hasZeroGstr2b
                        ? "Zero GSTR-2B Records Detected"
                        : "Zero Purchase Register Records Detected"}
                    </p>
                    <p className="text-xs text-amber-900/90 leading-relaxed">
                      {hasZeroGstr2b && hasZeroPr
                        ? "Both datasets are empty for this period. Starting reconciliation will produce an empty match result."
                        : hasZeroGstr2b
                        ? `Zero GSTR-2B records found for this period. Starting reconciliation will match 0 invoices and classify all ${run?.pr_record_count ?? 0} Purchase Register records as 'Missing in GSTR-2B (ITC at Risk)'. If your client or their suppliers file quarterly or haven't filed yet, verify the filing period before continuing.`
                        : `Zero Purchase Register records provided. Starting reconciliation will classify all ${run?.gstr2b_record_count ?? 0} GSTR-2B records as 'Missing in Books (Missed ITC)'.`}
                    </p>
                  </div>
                </div>
                <label className="flex items-center gap-2 pt-1 border-t border-amber-200/80 cursor-pointer text-xs font-semibold text-amber-950">
                  <input
                    type="checkbox"
                    checked={zeroRecordConfirmed}
                    onChange={(e) => setZeroRecordConfirmed(e.target.checked)}
                    className="h-4 w-4 rounded border-amber-400 text-amber-600 focus:ring-amber-500"
                  />
                  <span>I understand that 0 invoices will match and want to proceed with this run</span>
                </label>
              </div>
            );
          })()}

          {start409 ? (
            <div className="rounded-lg border border-[var(--warning)] bg-amber-50 p-3 text-sm">
              {extractErrorMessage(start409, "Cannot start.")}
            </div>
          ) : null}

          <button
            type="button"
            disabled={
              startBusy ||
              run?.status === "error" ||
              !highRiskWarningsOk ||
              (((run?.gstr2b_record_count ?? 0) === 0 || (run?.pr_record_count ?? 0) === 0) &&
                !zeroRecordConfirmed)
            }
            onClick={onStart}
            className="rounded-full bg-[var(--ink)] px-4 py-2 text-sm font-semibold text-white transition-opacity disabled:opacity-50 hover:opacity-90"
          >
            Start reconciliation
          </button>
        </div>
      ) : null}
    </div>
  );
}
