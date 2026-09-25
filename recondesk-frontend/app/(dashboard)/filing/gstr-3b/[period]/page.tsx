"use client";

import Link from "next/link";
import { useParams, useRouter, useSearchParams } from "next/navigation";
import { Suspense, useCallback, useEffect, useMemo, useState } from "react";
import { ArrowLeft, Download, FileCheck, CheckCircle2, AlertCircle, Loader2 } from "lucide-react";
import useSWR from "swr";

import { Gstr3bEvcAndFilePanel } from "@/components/filing/gstr3b/Gstr3bEvcAndFilePanel";
import { Gstr3bFiguresForm } from "@/components/filing/gstr3b/Gstr3bFiguresForm";
import { Gstr3bSaveAction } from "@/components/filing/gstr3b/Gstr3bSaveAction";
import {
  OffsetLiabilityGate,
  type Gstr3bRunState,
} from "@/components/filing/gstr3b/OffsetLiabilityGate";
import {
  emptyGstr3bFigures,
  figuresToSaveBody,
  type Gstr3bFiguresState,
  type ItcOthSuggestion,
  type OutwardSuggestion,
  type SuggestionLoadResult,
} from "@/components/filing/gstr3b/figuresModel";
import { GstnSessionPanel } from "@/components/filing/GstnSessionPanel";
import { toFilingPeriodYyyyMm } from "@/components/filing/filingHelpers";
import { downloadJsonFile } from "@/components/filing/downloadJsonFile";
import {
  pageContentClass,
  sectionContainerClass,
  SectionHeader,
} from "@/components/reconcile/ResultsUi";
import {
  clientsApi,
  filingApi,
  gstr3bFilingApi,
  isApiError,
  type ClientGstin,
  type Gstr3bTable4SuggestionResponse,
} from "@/lib/api";
import { useAccessToken } from "@/lib/hooks/useAccessToken";

const EMPTY_RUN: Gstr3bRunState = {
  runId: null,
  referenceId: null,
  serverRunStatus: null,
  gstnStatusCd: null,
  errorMessage: null,
  actionError: null,
};

function periodToRetPeriod(yyyyMm: string): string {
  const [y, m] = yyyyMm.split("-");
  return `${m}${y}`;
}

function Gstr3bFilingPageContent() {
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
  const [sessionId, setSessionId] = useState<string | null>(null);
  const [runState, setRunState] = useState<Gstr3bRunState>(EMPTY_RUN);
  const [figures, setFigures] = useState<Gstr3bFiguresState>(() =>
    emptyGstr3bFigures("", "")
  );

  const clientsKey = token ? (["filing-clients-3b", token] as const) : null;
  const { data: clients, isLoading: clientsLoading } = useSWR(
    clientsKey,
    ([, t]) => clientsApi.list(t)
  );

  const { data: filingFeatures, isLoading: featuresLoading } = useSWR(
    "filing-features",
    () => filingApi.features()
  );
  const gstr3bFilingEnabled = filingFeatures?.gstr3b_filing_enabled === true;

  const selectedClient: ClientGstin | null = useMemo(() => {
    if (!clients || !clientGstinId) return null;
    return clients.find((c) => c.id === clientGstinId) ?? null;
  }, [clients, clientGstinId]);

  const gstin = selectedClient?.gstin?.trim().toUpperCase() || "";
  const retPeriod = period ? periodToRetPeriod(period) : "";

  useEffect(() => {
    if (clientFromQuery) setClientGstinId(clientFromQuery);
  }, [clientFromQuery]);

  useEffect(() => {
    setRunState(EMPTY_RUN);
    setFigures(emptyGstr3bFigures(gstin, retPeriod));
  }, [clientGstinId, period, gstin, retPeriod]);

  const detailsKey =
    token && period && clientGstinId && sessionId
      ? (["gstr3b-details", token, period, clientGstinId, sessionId] as const)
      : null;
  const { data: detailsData } = useSWR(detailsKey, ([, t, p, cid, sid]) =>
    gstr3bFilingApi.details(t, p, { client_gstin_id: cid, session_id: sid })
  );

  useEffect(() => {
    if (!detailsData?.details) return;
    const intrLtfee = detailsData.details.intr_ltfee as
      | Record<string, unknown>
      | undefined;
    const ltfee = intrLtfee?.ltfee_details as
      | Record<string, unknown>
      | undefined;
    if (ltfee) {
      const camt = Number(ltfee.camt) || "";
      const samt = Number(ltfee.samt) || "";
      setFigures((prev) => ({
        ...prev,
        intr_ltfee: {
          ...prev.intr_ltfee,
          ltfee_details: {
            camt: camt,
            samt: samt,
          },
        },
      }));
    }
  }, [detailsData]);

  const loadOutwardSuggestion = useCallback(async (): Promise<
    SuggestionLoadResult<OutwardSuggestion>
  > => {
    if (!token || !clientGstinId || !period) {
      return { status: "unavailable", reason: "no_gstr1_reconcile_run" };
    }
    const res = await gstr3bFilingApi.suggestOsupDet(token, period, {
      client_gstin_id: clientGstinId,
    });
    if (!res.available || !res.osup_det) {
      return {
        status: "unavailable",
        reason: res.reason || "no_gstr1_aggregate",
      };
    }
    return {
      status: "available",
      suggestion: {
        source: res.source || "GSTR-1 Table 3.1(a)",
        osup_det: res.osup_det,
      },
    };
  }, [token, clientGstinId, period]);

  const loadOthSuggestion = useCallback(async (): Promise<
    SuggestionLoadResult<ItcOthSuggestion>
  > => {
    if (!token || !clientGstinId || !period) {
      return { status: "unavailable", reason: "no_gstr2b_reconcile_run" };
    }
    const res = await gstr3bFilingApi.suggestItcOth(token, period, {
      client_gstin_id: clientGstinId,
    });
    if (!res.available) {
      return {
        status: "unavailable",
        reason: res.reason || "no_gstr2b_records",
      };
    }
    return {
      status: "available",
      suggestion: {
        source: res.source || "GSTR-2B Table 4.1(A) OTH",
        iamt: res.iamt,
        camt: res.camt,
        samt: res.samt,
        csamt: res.csamt,
      },
    };
  }, [token, clientGstinId, period]);

  const loadTable4Suggestion = useCallback(async (): Promise<Gstr3bTable4SuggestionResponse> => {
    if (!token || !clientGstinId || !period) {
      return {
        available: false,
        status: "unavailable",
        period: period || "",
        client_gstin_id: clientGstinId || "",
        reason: "missing_client_or_period",
      };
    }
    return await gstr3bFilingApi.suggestTable4(token, period, {
      client_gstin_id: clientGstinId,
    });
  }, [token, clientGstinId, period]);

  const [exportingJson, setExportingJson] = useState(false);
  const [exportSuccess, setExportSuccess] = useState<string | null>(null);
  const [exportError, setExportError] = useState<string | null>(null);

  const handleExportJson = useCallback(async () => {
    if (!token || !clientGstinId || !period) return;
    setExportingJson(true);
    setExportError(null);
    setExportSuccess(null);
    try {
      const res = await gstr3bFilingApi.exportJson(token, period, {
        client_gstin_id: clientGstinId,
        figures: figuresToSaveBody(figures),
      });
      downloadJsonFile(res.filename, res.payload);
      const taxNote =
        res.summary?.total_tax_liability != null
          ? ` (Tax liability: ₹${res.summary.total_tax_liability.toLocaleString("en-IN")})`
          : "";
      setExportSuccess(`Successfully downloaded ${res.filename}${taxNote}`);
    } catch (err: unknown) {
      setExportError(
        isApiError(err)
          ? err.detail
          : err instanceof Error
            ? err.message
            : "Failed to export GSTR-3B JSON"
      );
    } finally {
      setExportingJson(false);
    }
  }, [token, clientGstinId, period, figures]);

  if (tokenState === null || featuresLoading) {
    return (
      <div className="flex min-h-[40vh] items-center justify-center px-8 text-[13px] text-gray-500">
        Loading…
      </div>
    );
  }

  if (!token) {
    return (
      <div className="mx-auto max-w-lg px-8 py-16 text-center">
        <p className="text-[14px] text-gray-500">Sign in to file GSTR-3B.</p>
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
          <code className="text-[13px]">/filing/gstr-3b/2026-07</code> (YYYY-MM).
        </p>
        <Link
          href="/filing/gstr-3b"
          className="mt-6 inline-flex rounded-full bg-[var(--ink)] px-5 py-2.5 text-[13px] font-semibold text-white"
        >
          Pick a period
        </Link>
      </div>
    );
  }

  return (
    <div className={pageContentClass}>
      <div className="mb-2 flex flex-col sm:flex-row sm:items-center sm:justify-between gap-4">
        <div className="flex items-center gap-4">
          <Link
            href="/filing/gstr-3b"
            className="inline-flex h-10 w-10 items-center justify-center rounded-full bg-white text-gray-500 shadow-[var(--shadow-soft)] transition hover:text-[var(--ink)]"
          >
            <ArrowLeft className="h-4 w-4" />
          </Link>
          <div>
            <h1 className="text-2xl font-semibold tracking-tight text-[var(--ink)]">
              File GSTR-3B
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
        {gstin && clientGstinId ? (
          <button
            type="button"
            disabled={exportingJson}
            onClick={() => void handleExportJson()}
            className="inline-flex items-center gap-2 self-start sm:self-center rounded-full border border-gray-300 bg-white px-4 py-2 text-xs font-semibold text-gray-800 shadow-xs hover:bg-gray-50 disabled:opacity-50 transition"
          >
            {exportingJson ? (
              <Loader2 className="h-3.5 w-3.5 animate-spin" />
            ) : (
              <Download className="h-3.5 w-3.5 text-blue-600" />
            )}
            <span>Download GSTN JSON (Offline Upload)</span>
          </button>
        ) : null}
      </div>

      <section className={sectionContainerClass}>
        <SectionHeader title="Client" dotColor="#111111" />
        <label className="mt-4 block max-w-lg">
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
      </section>

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
        <Gstr3bFiguresForm
          gstin={gstin}
          retPeriod={retPeriod}
          value={figures}
          onChange={setFigures}
          onLoadOutwardSuggestion={loadOutwardSuggestion}
          onLoadOthSuggestion={loadOthSuggestion}
          onLoadTable4Suggestion={loadTable4Suggestion}
          readOnly={
            runState.serverRunStatus === "offset_complete" ||
            runState.serverRunStatus === "evc_pending" ||
            runState.serverRunStatus === "filed"
          }
        />
      ) : null}

      {gstin && clientGstinId ? (
        <Gstr3bSaveAction
          token={token}
          period={period}
          clientGstinId={clientGstinId}
          sessionId={sessionId}
          figures={figures}
          runState={runState}
          onRunState={setRunState}
        />
      ) : null}

      {gstin && clientGstinId ? (
        <section className={sectionContainerClass}>
          <SectionHeader title="GST Portal Offline Upload" dotColor="#2563eb" />
          <p className="mt-1 text-[13px] text-gray-500">
            Export the official GSTN offline JSON to file this return on{" "}
            <code className="text-gray-700 font-mono">services.gst.gov.in</code>.
          </p>

          {exportSuccess ? (
            <div className="mt-4 flex items-center gap-2 rounded-xl bg-emerald-50 px-4 py-3 text-[13px] text-emerald-800 border border-emerald-200">
              <CheckCircle2 className="h-4 w-4 shrink-0 text-emerald-600" />
              <span>{exportSuccess}</span>
            </div>
          ) : null}

          {exportError ? (
            <div className="mt-4 flex items-center gap-2 rounded-xl bg-rose-50 px-4 py-3 text-[13px] text-rose-800 border border-rose-200">
              <AlertCircle className="h-4 w-4 shrink-0 text-rose-600" />
              <span>{exportError}</span>
            </div>
          ) : null}

          <div className="mt-4 flex flex-wrap items-center gap-3">
            <button
              type="button"
              disabled={exportingJson}
              onClick={() => void handleExportJson()}
              className="inline-flex items-center gap-2 rounded-full bg-blue-600 px-5 py-2.5 text-[13px] font-semibold text-white shadow-xs hover:bg-blue-700 transition disabled:opacity-50"
            >
              {exportingJson ? (
                <Loader2 className="h-4 w-4 animate-spin" />
              ) : (
                <Download className="h-4 w-4" />
              )}
              <span>Download Official GSTR-3B JSON</span>
            </button>
            <span className="text-[12px] text-gray-400">
              Upload via GST Portal → Returns Dashboard → GSTR-3B → Prepare Offline
            </span>
          </div>
        </section>
      ) : null}

      {gstin && clientGstinId && !gstr3bFilingEnabled ? (
        <section className="rounded-2xl border border-blue-200 bg-blue-50/60 p-5 text-blue-900 shadow-xs">
          <div className="flex items-start gap-3">
            <FileCheck className="h-5 w-5 shrink-0 text-blue-600 mt-0.5" />
            <div>
              <h4 className="text-[13px] font-semibold text-blue-950">
                Direct GSTN API Offset & Filing Disabled in this Environment
              </h4>
              <p className="mt-1 text-[12px] text-blue-800 leading-relaxed">
                Direct electronic ledger cash/ITC offset and EVC filing via API are protected. Use the <strong>Download Official GSTR-3B JSON</strong> button above to upload and file on <code className="text-blue-900 font-mono">services.gst.gov.in</code>.
              </p>
            </div>
          </div>
        </section>
      ) : null}

      {gstin && clientGstinId && gstr3bFilingEnabled ? (
        <OffsetLiabilityGate
          token={token}
          period={period}
          clientGstinId={clientGstinId}
          sessionId={sessionId}
          runState={runState}
          onRunState={setRunState}
        />
      ) : null}

      {gstin && clientGstinId && gstr3bFilingEnabled ? (
        <Gstr3bEvcAndFilePanel
          token={token}
          period={period}
          gstin={gstin}
          sessionId={sessionId}
          runState={runState}
          onRunState={setRunState}
        />
      ) : null}
    </div>
  );
}

export default function Gstr3bFilingPage() {
  return (
    <Suspense
      fallback={
        <div className="flex min-h-[40vh] items-center justify-center px-8 text-[13px] text-gray-500">
          Loading…
        </div>
      }
    >
      <Gstr3bFilingPageContent />
    </Suspense>
  );
}
