"use client";

import Link from "next/link";
import { useParams, useRouter, useSearchParams } from "next/navigation";
import { Suspense, useCallback, useEffect, useMemo, useState } from "react";
import { ArrowLeft, Loader2, Download, CheckCircle2 } from "lucide-react";
import useSWR from "swr";

import { downloadJsonFile } from "@/components/filing/downloadJsonFile";

import { ExternalInputGapsPanel } from "@/components/filing/ExternalInputGapsPanel";
import { EvcAndFilePanel } from "@/components/filing/EvcAndFilePanel";
import { FilingReadinessSummary } from "@/components/filing/FilingReadinessSummary";
import { GstnSessionPanel } from "@/components/filing/GstnSessionPanel";
import { PendingReviewQueue } from "@/components/filing/PendingReviewQueue";
import { Gstr1PortalMirrorView } from "@/components/filing/Gstr1PortalMirrorView";
import {
  SaveToGstnAction,
  type SaveServerState,
} from "@/components/filing/SaveToGstnAction";
import { MakerCheckerApprovalCard } from "@/components/filing/MakerCheckerApprovalCard";
import { ClientAuthorizationCard } from "@/components/filing/ClientAuthorizationCard";
import type { Gstr1PatchRecord } from "@/lib/gstr1PatchVoucher";
import { toFilingPeriodYyyyMm } from "@/components/filing/filingHelpers";
import {
  SectionHeader,
  pageContentClass,
  sectionContainerClass,
} from "@/components/reconcile/ResultsUi";
import {
  clientsApi,
  filingApi,
  isApiError,
  type ClientGstin,
  type FilingReadinessResponse,
} from "@/lib/api";
import { useAccessToken } from "@/lib/hooks/useAccessToken";

const EMPTY_SAVE: SaveServerState = {
  runId: null,
  referenceId: null,
  serverRunStatus: null,
  gstnStatusCd: null,
  errorMessage: null,
  actionError: null,
};

function Gstr1FilingPageContent() {
  const params = useParams();
  const searchParams = useSearchParams();
  const router = useRouter();
  const tokenState = useAccessToken();
  const token =
    typeof tokenState === "string" && tokenState.length > 0 ? tokenState : null;

  const periodParam = String(params.period || "");
  const period = toFilingPeriodYyyyMm(decodeURIComponent(periodParam));
  const clientFromQuery =
    searchParams.get("client_gstin_id")?.trim() || "";

  const [clientGstinId, setClientGstinId] = useState(clientFromQuery);
  const [srFile, setSrFile] = useState<File | null>(null);
  const [readiness, setReadiness] = useState<FilingReadinessResponse | null>(
    null
  );
  const [readinessBusy, setReadinessBusy] = useState(false);
  const [readinessError, setReadinessError] = useState<string | null>(null);
  const [sessionId, setSessionId] = useState<string | null>(null);
  const [saveState, setSaveState] = useState<SaveServerState>(EMPTY_SAVE);
  const [patches, setPatches] = useState<Gstr1PatchRecord[]>([]);

  const clientsKey = token ? (["filing-clients", token] as const) : null;
  const { data: clients, isLoading: clientsLoading } = useSWR(
    clientsKey,
    ([, t]) => clientsApi.list(t)
  );

  const selectedClient: ClientGstin | null = useMemo(() => {
    if (!clients || !clientGstinId) return null;
    return clients.find((c) => c.id === clientGstinId) ?? null;
  }, [clients, clientGstinId]);

  useEffect(() => {
    if (clientFromQuery) setClientGstinId(clientFromQuery);
  }, [clientFromQuery]);

  // Changing SR / client / period invalidates prior Save confirmation, readiness, and patches.
  useEffect(() => {
    setSaveState(EMPTY_SAVE);
    setPatches([]);
  }, [clientGstinId, period, srFile]);

  const runReadiness = useCallback(
    async (overridePatches?: Gstr1PatchRecord[]) => {
      if (!token || !period || !clientGstinId || !srFile) {
        setReadinessError(
          "Select a client, confirm the period (YYYY-MM), and upload a Sales Register."
        );
        return;
      }
      setReadinessBusy(true);
      setReadinessError(null);
      setReadiness(null);
      const activePatches = overridePatches ?? patches;
      try {
        const res = await filingApi.readinessUpload(token, period, {
          client_gstin_id: clientGstinId,
          sales_register_file: srFile,
          patches:
            activePatches.length > 0
              ? activePatches.map((p) => p.patch_data)
              : undefined,
        });
        setReadiness(res);
        // Fresh readiness must not imply Save succeeded.
        setSaveState(EMPTY_SAVE);
      } catch (err) {
        setReadiness(null);
        setReadinessError(
          isApiError(err)
            ? err.detail
            : err instanceof Error
              ? err.message
              : "Readiness check failed"
        );
      } finally {
        setReadinessBusy(false);
      }
    },
    [clientGstinId, patches, period, srFile, token]
  );

  const handleApplyPatch = useCallback(
    (patch: Gstr1PatchRecord) => {
      const nextPatches = [
        ...patches.filter(
          (p) =>
            (p.row_number != null && patch.row_number != null
              ? p.row_number !== patch.row_number
              : true) && p.invoice_number !== patch.invoice_number
        ),
        patch,
      ];
      setPatches(nextPatches);
      void runReadiness(nextPatches);
    },
    [patches, runReadiness]
  );

  const handleRemovePatch = useCallback(
    (invNum: string) => {
      const nextPatches = patches.filter((p) => p.invoice_number !== invNum);
      setPatches(nextPatches);
      void runReadiness(nextPatches);
    },
    [patches, runReadiness]
  );

  const [exportBusy, setExportBusy] = useState(false);
  const [exportSuccess, setExportSuccess] = useState<string | null>(null);
  const [exportError, setExportError] = useState<string | null>(null);

  const handleExportJson = useCallback(async () => {
    if (!token || !period || !clientGstinId || !srFile) {
      setExportError("Please upload a Sales Register file first.");
      return;
    }
    setExportBusy(true);
    setExportError(null);
    setExportSuccess(null);
    try {
      const res = await filingApi.exportGstr1JsonUpload(token, period, {
        client_gstin_id: clientGstinId,
        sales_register_file: srFile,
        patches:
          patches.length > 0
            ? patches.map((p) => p.patch_data)
            : undefined,
      });
      downloadJsonFile(res.filename, res.payload);
      const counts = [
        res.summary.b2b ? `${res.summary.b2b} B2B` : null,
        res.summary.b2cs ? `${res.summary.b2cs} B2CS` : null,
        res.summary.cdnr ? `${res.summary.cdnr} CDNR` : null,
        res.summary.hsn ? `${res.summary.hsn} HSN` : null,
      ]
        .filter(Boolean)
        .join(", ");
      setExportSuccess(
        `Downloaded ${res.filename} (${counts || `${res.record_count} records`}). Ready for direct upload to GST portal!`
      );
    } catch (err) {
      setExportError(
        isApiError(err)
          ? err.detail
          : err instanceof Error
            ? err.message
            : "Failed to export GSTN JSON"
      );
    } finally {
      setExportBusy(false);
    }
  }, [clientGstinId, patches, period, srFile, token]);

  if (tokenState === null) {
    return (
      <div className="flex min-h-[40vh] items-center justify-center px-8 text-[13px] text-gray-500">
        Loading…
      </div>
    );
  }

  if (!token) {
    return (
      <div className="mx-auto max-w-lg px-8 py-16 text-center">
        <p className="text-[14px] text-gray-500">Sign in to file GSTR-1.</p>
      </div>
    );
  }

  if (!period) {
    return (
      <div className="mx-auto max-w-lg px-8 py-16 text-center">
        <h1 className="text-xl font-semibold text-[var(--ink)]">
          Invalid filing period
        </h1>
        <p className="mt-2 text-[14px] text-gray-500">
          Use a path like{" "}
          <code className="text-[13px]">/filing/gstr-1/2026-07</code> (YYYY-MM).
        </p>
        <Link
          href="/reconcile/gstr1/new"
          className="mt-6 inline-flex rounded-full bg-[var(--ink)] px-5 py-2.5 text-[13px] font-semibold text-white"
        >
          Go to GSTR-1 reconcile
        </Link>
      </div>
    );
  }

  const gstin = readiness?.gstin || selectedClient?.gstin || "";

  return (
    <div className={pageContentClass}>
      <div className="mb-2 flex items-center gap-4">
        <Link
          href="/reconcile/gstr1/results"
          className="inline-flex h-10 w-10 items-center justify-center rounded-full bg-white text-gray-500 shadow-[var(--shadow-soft)] transition hover:text-[var(--ink)]"
        >
          <ArrowLeft className="h-4 w-4" />
        </Link>
        <div>
          <h1 className="text-2xl font-semibold tracking-tight text-[var(--ink)]">
            File GSTR-1
          </h1>
          <p className="text-sm text-gray-500">
            Period {period}
            {gstin ? ` · ${gstin}` : ""}
            {selectedClient?.trade_name
              ? ` · ${selectedClient.trade_name}`
              : ""}
          </p>
        </div>
      </div>

      <section className={sectionContainerClass} id="sr-upload">
        <SectionHeader title="Sales Register" dotColor="#111111" />
        <p className="mt-1 text-[13px] text-gray-500">
          Source of truth for Save. After fixing inv_typ / note / export types
          in the register, re-upload here and re-check readiness.
        </p>

        <div className="mt-4 grid gap-3 lg:grid-cols-2">
          <label className="block">
            <span className="text-[12px] font-medium text-gray-500">
              Client GSTIN
            </span>
            <select
              value={clientGstinId}
              onChange={(e) => {
                setClientGstinId(e.target.value);
                const q = new URLSearchParams(searchParams.toString());
                if (e.target.value) q.set("client_gstin_id", e.target.value);
                else q.delete("client_gstin_id");
                router.replace(`?${q.toString()}`);
              }}
              disabled={clientsLoading}
              className="mt-1.5 h-10 w-full appearance-none rounded-full border-0 bg-[#F5F5F6] px-4 text-[13px] font-medium text-[var(--ink)] outline-none focus:ring-2 focus:ring-black/10"
            >
              <option value="">Select client…</option>
              {(clients || []).map((c) => (
                <option key={c.id} value={c.id}>
                  {(c.trade_name || c.gstin || c.id).trim()} · {c.gstin}
                </option>
              ))}
            </select>
          </label>

          <label className="block">
            <span className="text-[12px] font-medium text-gray-500">
              Sales Register file
            </span>
            <input
              type="file"
              accept=".xlsx,.xls,.csv"
              className="mt-1.5 block w-full text-[13px] text-gray-600 file:mr-3 file:rounded-full file:border-0 file:bg-[#F5F5F6] file:px-4 file:py-2 file:text-[13px] file:font-semibold file:text-gray-700 hover:file:bg-gray-200/70"
              onChange={(e) => setSrFile(e.target.files?.[0] ?? null)}
            />
            {srFile ? (
              <p className="mt-2 truncate text-[12px] text-gray-500">
                {srFile.name} · {(srFile.size / 1024).toFixed(1)} KB
              </p>
            ) : null}
          </label>
        </div>

        <div className="mt-4 flex flex-wrap items-center gap-3">
          <button
            type="button"
            disabled={readinessBusy || !srFile || !clientGstinId}
            onClick={() => void runReadiness()}
            className="inline-flex items-center gap-2 rounded-full bg-[var(--ink)] px-5 py-2.5 text-[13px] font-semibold text-white hover:opacity-90 disabled:opacity-40"
          >
            {readinessBusy ? (
              <Loader2 className="h-4 w-4 animate-spin" />
            ) : null}
            Check readiness
          </button>

          <button
            type="button"
            disabled={exportBusy || !srFile || !clientGstinId}
            onClick={() => void handleExportJson()}
            className="inline-flex items-center gap-2 rounded-full border border-gray-300 bg-white px-5 py-2.5 text-[13px] font-semibold text-gray-700 shadow-sm transition hover:bg-gray-50 disabled:opacity-40"
          >
            {exportBusy ? (
              <Loader2 className="h-4 w-4 animate-spin" />
            ) : (
              <Download className="h-4 w-4 text-gray-500" />
            )}
            Download GSTN JSON (Offline Upload)
          </button>
        </div>

        {exportSuccess ? (
          <div className="mt-3 flex items-center gap-2 rounded-xl bg-emerald-50 px-4 py-3 text-[13px] font-medium text-emerald-800 ring-1 ring-emerald-200">
            <CheckCircle2 className="h-4 w-4 shrink-0 text-emerald-600" />
            <span>{exportSuccess}</span>
          </div>
        ) : null}

        {exportError ? (
          <div className="mt-3 rounded-xl bg-red-50 px-4 py-3 text-[13px] text-red-600 ring-1 ring-red-200">
            {exportError}
          </div>
        ) : null}

        {readinessError ? (
          <div className="mt-3 rounded-xl bg-[#F7F7F8] px-4 py-3 text-[13px] text-[var(--ink)] ring-1 ring-[#E8E8EA]">
            {readinessError}
          </div>
        ) : null}
      </section>

      {readiness ? (
        <>
          <FilingReadinessSummary
            verdict={readiness.filing_readiness}
            recordCount={readiness.record_count}
          />
          {readiness.portal_mirror ? (
            <Gstr1PortalMirrorView
              mirror={readiness.portal_mirror}
              filingPeriod={period}
            />
          ) : null}
          <ExternalInputGapsPanel gaps={readiness.external_input_gaps} />
          <PendingReviewQueue
            items={readiness.pending_review}
            byTable={readiness.pending_review_by_table}
            reUploadHref="#sr-upload"
            patches={patches}
            onApplyPatch={handleApplyPatch}
            onRemovePatch={handleRemovePatch}
            onRecheckReadiness={() => void runReadiness()}
            filingPeriod={period}
            gstin={gstin}
            companyName={
              selectedClient?.trade_name || selectedClient?.legal_name || ""
            }
          />
        </>
      ) : null}

      {gstin && clientGstinId ? (
        <GstnSessionPanel
          token={token}
          gstin={gstin}
          clientGstinId={clientGstinId}
          sessionId={sessionId}
          onSessionId={setSessionId}
        />
      ) : null}

      {gstin && clientGstinId ? (
        <MakerCheckerApprovalCard
          token={token}
          clientGstinId={clientGstinId}
          gstin={gstin}
          period={period}
          returnType="GSTR-1"
          preparedFigures={
            readiness?.portal_mirror
              ? (readiness.portal_mirror as unknown as Record<string, unknown>)
              : null
          }
        />
      ) : null}

      {gstin && clientGstinId ? (
        <ClientAuthorizationCard
          token={token}
          clientGstinId={clientGstinId}
          gstin={gstin}
          period={period}
          returnType="GSTR-1"
          preparedFigures={
            readiness?.portal_mirror
              ? (readiness.portal_mirror as unknown as Record<string, unknown>)
              : null
          }
        />
      ) : null}

      <SaveToGstnAction
        token={token}
        period={period}
        clientGstinId={clientGstinId}
        srFile={srFile}
        sessionId={sessionId}
        canSaveHint={!!readiness?.filing_readiness.can_save}
        serverState={saveState}
        onServerState={setSaveState}
        patches={
          patches.length > 0 ? patches.map((p) => p.patch_data) : undefined
        }
      />

      <EvcAndFilePanel
        token={token}
        period={period}
        gstin={gstin}
        sessionId={sessionId}
        saveState={saveState}
        onSaveState={setSaveState}
      />
    </div>
  );
}

export default function Gstr1FilingPage() {
  return (
    <Suspense
      fallback={
        <div className="flex min-h-[40vh] items-center justify-center px-8 text-[13px] text-gray-500">
          Loading…
        </div>
      }
    >
      <Gstr1FilingPageContent />
    </Suspense>
  );
}
