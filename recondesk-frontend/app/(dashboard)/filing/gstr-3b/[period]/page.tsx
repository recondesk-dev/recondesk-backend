"use client";

import Link from "next/link";
import { useParams, useRouter, useSearchParams } from "next/navigation";
import { Suspense, useCallback, useEffect, useMemo, useState } from "react";
import { ArrowLeft } from "lucide-react";
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
  type Gstr3bFiguresState,
  type ItcOthSuggestion,
  type OutwardSuggestion,
} from "@/components/filing/gstr3b/figuresModel";
import { GstnSessionPanel } from "@/components/filing/GstnSessionPanel";
import { toFilingPeriodYyyyMm } from "@/components/filing/filingHelpers";
import {
  pageContentClass,
  sectionContainerClass,
  SectionHeader,
} from "@/components/reconcile/ResultsUi";
import { clientsApi, type ClientGstin } from "@/lib/api";
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

  const loadOutwardSuggestion = useCallback(async (): Promise<OutwardSuggestion | null> => {
    // Explicit action only — no auto-fetch on mount.
    // Wire to GSTR-1 reconcile aggregate when a dedicated source exists.
    return null;
  }, []);

  const loadOthSuggestion = useCallback(async (): Promise<ItcOthSuggestion | null> => {
    return null;
  }, []);

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
      <div className="mb-2 flex items-center gap-4">
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
        <OffsetLiabilityGate
          token={token}
          period={period}
          clientGstinId={clientGstinId}
          sessionId={sessionId}
          runState={runState}
          onRunState={setRunState}
        />
      ) : null}

      {gstin && clientGstinId ? (
        <Gstr3bEvcAndFilePanel
          token={token}
          period={period}
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
