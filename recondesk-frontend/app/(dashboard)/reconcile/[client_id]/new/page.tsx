"use client";

import Link from "next/link";
import { useParams, useRouter, useSearchParams } from "next/navigation";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  importWizardApi,
  type ApiError,
  type ColumnMappingRow,
  type ImportWizardRun,
  type SanityCheckItem,
} from "@/lib/api";
import { createClient, subscribeAccessToken } from "@/lib/supabase/client";

const MAX_UPLOAD = 20 * 1024 * 1024;
const ACTIVE_STATUSES = ["draft", "gstr_uploaded", "pr_uploaded", "pending", "processing"] as const;

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

function pastMonthOptions(): { value: string; label: string }[] {
  const out: { value: string; label: string }[] = [];
  const d = new Date();
  let y = d.getFullYear();
  let m = d.getMonth();
  if (m === 0) {
    y -= 1;
    m = 11;
  } else {
    m -= 1;
  }
  const fmt = new Intl.DateTimeFormat("en-IN", { month: "long", year: "numeric" });
  for (let i = 0; i < 12; i++) {
    const mm = String(m + 1).padStart(2, "0");
    const value = `${y}-${mm}-01`;
    const label = fmt.format(new Date(y, m, 1));
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

function initialUiStep(run: ImportWizardRun | null): number {
  if (!run) return 1;
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
                    ? "bg-[var(--accent)] text-white"
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
  const [gstrProgress, setGstrProgress] = useState(0);
  const [gstrUploadFailed, setGstrUploadFailed] = useState(false);
  const [sanityChecks, setSanityChecks] = useState<SanityCheckItem[] | null>(null);
  const [sanityBusy, setSanityBusy] = useState(false);

  const [prFile, setPrFile] = useState<File | null>(null);
  const [prProgress, setPrProgress] = useState(0);
  const [prUploadFailed, setPrUploadFailed] = useState(false);
  const [detectBusy, setDetectBusy] = useState(false);
  const [allHeaders, setAllHeaders] = useState<string[]>([]);
  const [mappingLocal, setMappingLocal] = useState<ColumnMappingRow[] | null>(null);

  const [startBusy, setStartBusy] = useState(false);
  const [start409, setStart409] = useState<string | null>(null);

  const [poll, setPoll] = useState<{ pct: number; message: string; status: string } | null>(null);
  const [pollSlow, setPollSlow] = useState(false);
  const pollStartRef = useRef<number | null>(null);

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
      const supabase = createClient();
      const qRunId = searchParams.get("run_id");
      if (qRunId) {
        try {
          const r = await importWizardApi.getRun(token, qRunId);
          if (r.client_id !== clientId) {
            setErr("This run does not belong to this client.");
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
  }, [token, clientId, searchParams]);

  useEffect(() => {
    if (!run?.id) return;
    if (run.sanity_check_results?.length) setSanityChecks(run.sanity_check_results);
    if (run.column_mapping?.length) {
      setMappingLocal(run.column_mapping);
      const h = run.pr_column_headers;
      if (h && Array.isArray(h)) setAllHeaders(h as string[]);
    }
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
    setBusy(true);
    try {
      // eslint-disable-next-line no-console -- debug: verify JWT sent on Continue
      const r = await importWizardApi.createRun(token, { client_id: clientId, period });
      setRun(r);
      setUiStep(2);
      router.replace(`/reconcile/${clientId}/new?run_id=${r.id}`);
    } catch (e) {
      const ae = e as ApiError;
      setErr(ae.detail ?? "Could not create run.");
    } finally {
      setBusy(false);
    }
  };

  const runId = run?.id ?? searchParams.get("run_id");

  const runSanityWithRetry = async () => {
    if (typeof token !== "string" || !runId) return;
    setSanityBusy(true);
    setErr(null);
    try {
      const res = await withRetries(
        () => importWizardApi.sanityCheckGstr2b(token, runId),
        3,
        1500
      );
      setSanityChecks(res.checks);
      await refreshRun(runId, token);
    } catch (e) {
      const ae = e as ApiError;
      setErr(ae.detail ?? "Sanity check failed.");
    } finally {
      setSanityBusy(false);
    }
  };

  const onGstrUpload = async () => {
    if (typeof token !== "string" || !runId || !gstrFile) return;
    setErr(null);
    setGstrUploadFailed(false);
    if (!gstrFile.name.toLowerCase().endsWith(".json")) {
      setErr("File must be a .json export.");
      return;
    }
    if (gstrFile.size > MAX_UPLOAD) {
      setErr("File must be under 20 MB.");
      return;
    }
    const text = await gstrFile.text();
    try {
      JSON.parse(text);
    } catch {
      setErr("This file is not valid JSON. Export again from the GST portal.");
      return;
    }
    const file = new File([text], gstrFile.name, { type: "application/json" });
    const hash = await sha256Hex(file);
    setBusy(true);
    setGstrProgress(0);
    try {
      const su = await importWizardApi.signedUrl(token, {
        type: "gstr2b",
        run_id: runId,
        file_name: file.name,
        content_type: "application/json",
      });
      await withRetries(
        () =>
          putWithProgress(su.upload_url, file, hash, su.headers["Content-Type"] ?? "application/json", setGstrProgress),
        3,
        2000
      );
      const updated = await importWizardApi.gstr2bUploadComplete(token, runId, {
        r2_key: su.key,
        file_name: file.name,
        file_size: file.size,
        file_hash: hash,
      });
      setRun(updated);
      await runSanityWithRetry();
    } catch {
      setGstrUploadFailed(true);
      setErr("Upload failed. Check your connection and try again.");
    } finally {
      setBusy(false);
    }
  };

  const onPrUpload = async () => {
    if (typeof token !== "string" || !runId || !prFile) return;
    setErr(null);
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
      });
      setRun(updated);
      await runDetectWithRetry();
    } catch {
      setPrUploadFailed(true);
      setErr("Upload failed. Check your connection and try again.");
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
      const r = await refreshRun(runId, token);
      setRun(r);
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
  const sanityErrors = checksDisplayed.filter((c) => c.status === "error");
  const sanityWarnings = checksDisplayed.filter((c) => c.status === "warning");
  const warningsOk = sanityWarnings.length === 0 || sanityWarnings.every((w) => w.acknowledged);

  const gstinRow = mappingLocal?.find((m) => m.standard_field === "gstin");
  const invRow = mappingLocal?.find((m) => m.standard_field === "invoice_number");
  const requiredOk =
    !!gstinRow?.detected_column &&
    !!invRow?.detected_column &&
    gstinRow.confidence !== "not_found" &&
    invRow.confidence !== "not_found";
  const lowOk =
    !mappingLocal ||
    mappingLocal.every((m) => {
      if (!m.detected_column) return true;
      if (m.confidence !== "low") return true;
      return m.confirmed;
    });

  const canGoToStep3 = sanityErrors.length === 0 && warningsOk && !!checksDisplayed.length;
  const canGoToStep4 = requiredOk && lowOk && !!mappingLocal?.length;

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
    try {
      await importWizardApi.start(token, runId);
      const r = await refreshRun(runId, token);
      setRun(r);
      pollStartRef.current = Date.now();
      setPollSlow(false);
      setPoll({ pct: 0, message: "Starting…", status: r.status });
    } catch (e) {
      const ae = e as ApiError;
      if (ae.status === 409) setStart409(ae.detail ?? "Cannot start.");
      else setErr(ae.detail ?? "Start failed.");
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
      const ae = e as ApiError;
      setErr(ae.detail ?? "Retry failed.");
    }
  };

  useEffect(() => {
    if (typeof token !== "string" || !runId) return;
    if (run?.status !== "pending" && run?.status !== "processing") return;

    let cancelled = false;
    const t0 = pollStartRef.current ?? Date.now();
    pollStartRef.current = t0;

    const tick = async () => {
      try {
        const s = await importWizardApi.pollStatus(token, runId);
        if (cancelled) return;
        setPoll({ pct: s.progress_pct, message: s.message, status: s.status });
        if (s.status === "complete") {
          router.push(`/results/${runId}`);
          return;
        }
        if (s.status === "error") {
          await refreshRun(runId, token);
          return;
        }
        if (Date.now() - t0 > 5 * 60 * 1000) setPollSlow(true);
      } catch {
        /* ignore transient poll errors */
      }
    };

    tick();
    const id = setInterval(tick, 3000);
    return () => {
      cancelled = true;
      clearInterval(id);
    };
  }, [token, runId, run?.status, router, refreshRun]);

  if (token === null) {
    return (
      <div className="flex min-h-[40vh] flex-col items-center justify-center gap-4 rounded-xl border border-[var(--border)] bg-[var(--surface)] p-8 text-[var(--text-secondary)]">
        <svg
          className="h-8 w-8 animate-spin text-[var(--accent)]"
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
      <div className="rounded-xl border border-[var(--border)] bg-[var(--surface)] p-8 text-[var(--text-secondary)]">
        Sign in to continue.
      </div>
    );
  }

  if (run?.status === "pending" || run?.status === "processing") {
    const pct = poll?.pct ?? run.progress_pct ?? 0;
    const msg = poll?.message || run.status_message || "Processing…";
    return (
      <div className="mx-auto max-w-lg space-y-6 rounded-xl border border-[var(--border)] bg-[var(--surface)] p-8">
        <h1 className="text-lg font-semibold text-[var(--text-primary)]">Reconciliation in progress</h1>
        <p className="text-[var(--text-primary)]">{msg}</p>
        <div className="h-3 w-full overflow-hidden rounded-full bg-[var(--border)]">
          <div
            className="h-full bg-[var(--accent)] transition-all"
            style={{ width: `${Math.min(100, pct)}%` }}
          />
        </div>
        <p className="font-mono text-sm text-[var(--text-secondary)]">{pct}%</p>
        {pollSlow ? (
          <p className="text-sm text-[var(--text-secondary)]">
            This is taking longer than expected. You can close this page — the run will continue in the background.
          </p>
        ) : null}
        <div className="flex flex-wrap gap-3">
          <button
            type="button"
            onClick={onCancelRun}
            className="rounded-lg border border-[var(--border)] px-4 py-2 text-sm font-medium text-[var(--text-primary)] hover:bg-[var(--bg)]"
          >
            Cancel run
          </button>
          <Link
            href="/"
            className="rounded-lg bg-[var(--accent)] px-4 py-2 text-sm font-medium text-white"
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
          <h1 className="text-xl font-semibold text-[var(--text-primary)]">New reconciliation</h1>
          <p className="text-sm text-[var(--text-secondary)]">
            Client: <span className="font-mono">{clientId}</span>
          </p>
        </div>
        <Link
          href={`/clients/${clientId}`}
          className="text-sm font-medium text-[var(--accent)] hover:underline"
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
              className="rounded-lg bg-[var(--accent)] px-4 py-2 text-sm font-medium text-white"
            >
              Resume
            </button>
            <button
              type="button"
              onClick={onStartFresh}
              disabled={busy}
              className="rounded-lg border border-[var(--border)] px-4 py-2 text-sm font-medium"
            >
              Start fresh
            </button>
          </div>
        </div>
      ) : null}

      {err ? (
        <div className="rounded-lg border border-[var(--danger)] bg-red-50 px-4 py-3 text-sm text-red-900">
          {err}
        </div>
      ) : null}

      {uiStep === 1 ? (
        <div className="space-y-4 rounded-xl border border-[var(--border)] bg-[var(--surface)] p-6">
          <h2 className="font-semibold text-[var(--text-primary)]">Select period</h2>
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
            disabled={!period || busy}
            onClick={onConfirmPeriod}
            className="rounded-lg bg-[var(--accent)] px-4 py-2 text-sm font-medium text-white disabled:opacity-50"
          >
            Continue
          </button>
        </div>
      ) : null}

      {uiStep === 2 && runId ? (
        <div className="space-y-4 rounded-xl border border-[var(--border)] bg-[var(--surface)] p-6">
          <div className="flex items-center justify-between">
            <h2 className="font-semibold text-[var(--text-primary)]">Upload GSTR-2B JSON</h2>
            <button type="button" onClick={onBack} className="text-sm text-[var(--accent)] hover:underline">
              Back
            </button>
          </div>
          {run?.gstr2b_file_name && !gstrFile ? (
            <p className="text-sm text-[var(--text-secondary)]">
              Uploaded: <strong>{run.gstr2b_file_name}</strong> ({formatBytes(run.gstr2b_file_size)})
            </p>
          ) : (
            <>
              <input
                type="file"
                accept=".json,application/json"
                onChange={(e) => setGstrFile(e.target.files?.[0] ?? null)}
                className="text-sm"
              />
              {gstrProgress > 0 && gstrProgress < 100 ? (
                <div className="space-y-1">
                  <div className="h-2 w-full overflow-hidden rounded bg-[var(--border)]">
                    <div
                      className="h-full bg-[var(--accent)]"
                      style={{ width: `${gstrProgress}%` }}
                    />
                  </div>
                  <p className="font-mono text-xs text-[var(--text-secondary)]">{gstrProgress}%</p>
                </div>
              ) : null}
              <button
                type="button"
                disabled={!gstrFile || busy}
                onClick={onGstrUpload}
                className="rounded-lg bg-[var(--accent)] px-4 py-2 text-sm font-medium text-white disabled:opacity-50"
              >
                Upload &amp; verify
              </button>
              {gstrUploadFailed ? (
                <button
                  type="button"
                  onClick={onGstrUpload}
                  className="ml-2 rounded-lg border px-4 py-2 text-sm"
                >
                  Retry upload
                </button>
              ) : null}
            </>
          )}

          {sanityBusy ? (
            <p className="text-sm text-[var(--text-secondary)]">Running sanity checks…</p>
          ) : null}

          {checksDisplayed.length ? (
            <div className="space-y-3">
              {sanityErrors.length ? (
                <div className="rounded-lg border border-[var(--danger)] bg-red-50 p-3 text-sm text-red-900">
                  Cannot proceed. Fix the issues below and re-upload.
                </div>
              ) : null}
              {sanityErrors.length === 0 && sanityWarnings.some((w) => !w.acknowledged) ? (
                <div className="rounded-lg border border-[var(--warning)] bg-amber-50 p-3 text-sm text-amber-950">
                  Review warnings before continuing.
                </div>
              ) : null}
              <ul className="space-y-2">
                {checksDisplayed.map((c) => (
                  <li
                    key={c.id}
                    className="flex flex-wrap items-start gap-2 rounded-lg border border-[var(--border)] p-3 text-sm"
                  >
                    {c.status === "pass" ? (
                      <span className="text-[var(--success)]">✓</span>
                    ) : c.status === "warning" ? (
                      <span className="text-[var(--warning)]">⚠</span>
                    ) : (
                      <span className="text-[var(--danger)]">✕</span>
                    )}
                    <div className="flex-1">
                      <div className="font-medium">{c.label}</div>
                      {c.detail ? <div className="text-[var(--text-secondary)]">{c.detail}</div> : null}
                      {c.affected_records?.length ? (
                        <ul className="mt-1 font-mono text-xs text-[var(--text-secondary)]">
                          {c.affected_records.slice(0, 20).map((a, i) => (
                            <li key={i}>
                              {a.gstin} — {a.invoice_number}
                            </li>
                          ))}
                        </ul>
                      ) : null}
                      {c.status === "warning" ? (
                        <button
                          type="button"
                          disabled={!!c.acknowledged}
                          onClick={() => onDismissWarning(c)}
                          className="mt-2 rounded border px-2 py-1 text-xs font-medium disabled:opacity-50"
                        >
                          {c.acknowledged ? "Dismissed" : "Dismiss"}
                        </button>
                      ) : null}
                    </div>
                  </li>
                ))}
              </ul>
              {sanityErrors.length ? (
                <button
                  type="button"
                  onClick={() => {
                    setGstrFile(null);
                    setSanityChecks(null);
                  }}
                  className="text-sm font-medium text-[var(--accent)]"
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
            className="rounded-lg bg-[var(--text-primary)] px-4 py-2 text-sm font-medium text-white disabled:opacity-50"
          >
            Continue to purchase register
          </button>
        </div>
      ) : null}

      {uiStep === 3 && runId ? (
        <div className="space-y-4 rounded-xl border border-[var(--border)] bg-[var(--surface)] p-6">
          <div className="flex items-center justify-between">
            <h2 className="font-semibold text-[var(--text-primary)]">Upload purchase register</h2>
            <button type="button" onClick={onBack} className="text-sm text-[var(--accent)] hover:underline">
              Back
            </button>
          </div>
          {run?.pr_file_name && !prFile ? (
            <p className="text-sm text-[var(--text-secondary)]">
              Uploaded: <strong>{run.pr_file_name}</strong> ({formatBytes(run.pr_file_size)})
            </p>
          ) : (
            <>
              <input
                type="file"
                accept=".csv,.xlsx,.xls"
                onChange={(e) => setPrFile(e.target.files?.[0] ?? null)}
                className="text-sm"
              />
              {prProgress > 0 && prProgress < 100 ? (
                <div className="space-y-1">
                  <div className="h-2 w-full overflow-hidden rounded bg-[var(--border)]">
                    <div className="h-full bg-[var(--accent)]" style={{ width: `${prProgress}%` }} />
                  </div>
                  <p className="font-mono text-xs text-[var(--text-secondary)]">{prProgress}%</p>
                </div>
              ) : null}
              <button
                type="button"
                disabled={!prFile || busy}
                onClick={onPrUpload}
                className="rounded-lg bg-[var(--accent)] px-4 py-2 text-sm font-medium text-white disabled:opacity-50"
              >
                Upload &amp; detect columns
              </button>
              {prUploadFailed ? (
                <button type="button" onClick={onPrUpload} className="ml-2 rounded-lg border px-4 py-2 text-sm">
                  Retry upload
                </button>
              ) : null}
            </>
          )}

          {detectBusy ? <p className="text-sm text-[var(--text-secondary)]">Detecting columns…</p> : null}

          {!requiredOk && mappingLocal?.length ? (
            <div className="rounded-lg border border-[var(--danger)] bg-red-50 p-3 text-sm text-red-900">
              Required columns could not be detected. Assign them manually.
            </div>
          ) : null}

          {mappingLocal?.length ? (
            <div className="overflow-x-auto">
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
                    const highlight =
                      row.confidence === "low" || row.confidence === "not_found" ? "bg-amber-50" : "";
                    const badge =
                      row.confidence === "high"
                        ? "bg-emerald-100 text-emerald-800"
                        : row.confidence === "medium"
                          ? "bg-amber-100 text-amber-900"
                          : "bg-red-100 text-red-800";
                    return (
                      <tr key={row.standard_field} className={`border-b border-[var(--border)] ${highlight}`}>
                        <td className="py-2 pr-3 font-medium">{row.standard_field}</td>
                        <td className="py-2 pr-3">{row.detected_column ?? "—"}</td>
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
          ) : null}

          <p className="text-xs text-[var(--text-secondary)]">
            Your files are processed on Indian servers, not shared with third parties, and deleted within 24 hours of run
            completion.
          </p>

          <button
            type="button"
            disabled={!canGoToStep4}
            onClick={() => setUiStep(4)}
            className="rounded-lg bg-[var(--text-primary)] px-4 py-2 text-sm font-medium text-white disabled:opacity-50"
          >
            Continue to start
          </button>
        </div>
      ) : null}

      {uiStep === 4 && runId ? (
        <div className="space-y-4 rounded-xl border border-[var(--border)] bg-[var(--surface)] p-6">
          <div className="flex items-center justify-between">
            <h2 className="font-semibold text-[var(--text-primary)]">Start reconciliation</h2>
            <button type="button" onClick={onBack} className="text-sm text-[var(--accent)] hover:underline">
              Back
            </button>
          </div>

          {run?.status === "error" ? (
            <div className="rounded-lg border border-[var(--danger)] bg-red-50 p-3 text-sm text-red-900">
              {run.error_detail || "Processing failed."}
              <div className="mt-2">
                <button
                  type="button"
                  onClick={onRetryError}
                  className="rounded-lg border border-[var(--border)] bg-white px-3 py-1 text-sm font-medium"
                >
                  Try again
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
            <p className="mt-3 font-medium text-[var(--text-primary)]">
              {run?.gstr2b_record_count ?? 0} GSTR-2B records vs {run?.pr_record_count ?? 0} Purchase Register records
            </p>
          </div>

          {start409 ? (
            <div className="rounded-lg border border-[var(--warning)] bg-amber-50 p-3 text-sm">{start409}</div>
          ) : null}

          <button
            type="button"
            disabled={startBusy || run?.status === "error"}
            onClick={onStart}
            className="rounded-lg bg-[var(--accent)] px-4 py-2 text-sm font-medium text-white disabled:opacity-50"
          >
            Start reconciliation
          </button>
        </div>
      ) : null}
    </div>
  );
}
