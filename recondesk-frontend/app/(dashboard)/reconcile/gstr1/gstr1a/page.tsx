"use client";

import Link from "next/link";
import { useSearchParams } from "next/navigation";
import { Suspense, useEffect, useState } from "react";

import { Gstr1aPeriodSummaryView } from "@/components/reconcile/Gstr1aPeriodSummaryView";
import { Gstr1aWorkbench } from "@/components/reconcile/Gstr1aWorkbench";
import {
  gstr1RunPeriodLabel,
  loadGstr1Result,
  loadGstr1ResultByRunId,
  loadGstr1RunId,
  type Gstr1ReconcileResult,
} from "@/lib/gstr1Reconcile";
import { useAccessToken } from "@/lib/hooks/useAccessToken";

function Gstr1aSummaryContent() {
  const searchParams = useSearchParams();
  const queryRunId = searchParams.get("run_id")?.trim() || null;
  const queryClientId = searchParams.get("client_gstin_id")?.trim() || searchParams.get("client_id")?.trim() || null;
  const queryPeriod = searchParams.get("period")?.trim() || null;
  const queryGstin = searchParams.get("gstin")?.trim() || null;

  const [activeTab, setActiveTab] = useState<"workbench" | "mismatches">(
    queryClientId && queryPeriod ? "workbench" : "mismatches"
  );

  const tokenState = useAccessToken();
  const token =
    typeof tokenState === "string" && tokenState.length > 0 ? tokenState : null;
  /** `null` until the first auth callback; `false` means signed out. */
  const tokenPending = tokenState === null;

  const [result, setResult] = useState<Gstr1ReconcileResult | null | undefined>(
    undefined
  );
  const [resolvedRunId, setResolvedRunId] = useState<string | null>(queryRunId);

  useEffect(() => {
    let cancelled = false;

    async function load() {
      const mem = loadGstr1Result();

      // In-memory result from the just-run reconciliation has priority when no explicit ?run_id= is passed.
      if (!queryRunId && mem) {
        if (!cancelled) {
          setResult(mem);
          setResolvedRunId(mem.run_id ? String(mem.run_id) : null);
        }
        return;
      }

      const runId = queryRunId || (mem?.run_id ? String(mem.run_id) : null) || loadGstr1RunId();
      if (!cancelled) setResolvedRunId(runId);

      if (runId) {
        if (tokenPending) return;
        if (!token) {
          if (!cancelled) setResult(null);
          return;
        }
        const memMatches =
          !!mem && (!mem.run_id || String(mem.run_id) === runId);
        if (memMatches && !cancelled) {
          setResult(mem);
        }
        const fromDb = await loadGstr1ResultByRunId(token, runId);
        if (cancelled) return;
        if (fromDb) {
          setResult(fromDb);
          return;
        }
        if (!memMatches) setResult(null);
        return;
      }

      if (!cancelled) {
        setResult(mem);
      }
    }

    void load();
    return () => {
      cancelled = true;
    };
  }, [queryRunId, token, tokenPending]);

  const clientGstinId = queryClientId || (result as any)?.client_gstin_id || null;
  const period = queryPeriod || (result ? gstr1RunPeriodLabel(result) : null) || null;
  const gstin = queryGstin || (result as any)?.parse_diagnostics?.gstr1?.filing_gstin || "Client GSTIN";

  if (result === undefined || (queryRunId && tokenPending)) {
    return (
      <div className="flex min-h-[40vh] items-center justify-center px-8">
        <p className="text-[13px] text-gray-500">Loading GSTR-1A summary…</p>
      </div>
    );
  }

  if (!result && !(clientGstinId && period)) {
    return (
      <div className="mx-auto flex min-h-[50vh] w-full max-w-lg flex-col items-center justify-center px-8 text-center">
        <h1 className="text-xl font-semibold tracking-tight text-[var(--ink)]">
          No GSTR-1 run loaded
        </h1>
        <p className="mt-2 text-[14px] text-gray-500">
          Open this summary from a completed GSTR-1 reconciliation result or practice dashboard.
        </p>
        <Link
          href="/reconcile/gstr1/new"
          className="mt-6 inline-flex min-h-[44px] items-center justify-center rounded-full bg-[var(--ink)] px-6 text-[13px] font-semibold text-white transition-opacity hover:opacity-90"
        >
          Start GSTR-1 Reconciliation
        </Link>
      </div>
    );
  }

  const effectiveRunId = result?.run_id ?? resolvedRunId ?? null;
  const backHref = effectiveRunId
    ? `/reconcile/gstr1/results?run_id=${encodeURIComponent(effectiveRunId)}`
    : "/reconcile/gstr1/results";

  return (
    <div className="space-y-4">
      {clientGstinId && period && result && (
        <div className="mx-auto max-w-7xl px-4 sm:px-6 lg:px-8 pt-4">
          <div className="flex items-center gap-4 border-b pb-2 text-xs font-medium text-gray-500">
            <button
              type="button"
              onClick={() => setActiveTab("workbench")}
              className={`pb-2 border-b-2 font-semibold ${
                activeTab === "workbench"
                  ? "border-indigo-600 text-indigo-600"
                  : "border-transparent hover:text-gray-900"
              }`}
            >
              Amendment Workbench
            </button>
            <button
              type="button"
              onClick={() => setActiveTab("mismatches")}
              className={`pb-2 border-b-2 font-semibold ${
                activeTab === "mismatches"
                  ? "border-indigo-600 text-indigo-600"
                  : "border-transparent hover:text-gray-900"
              }`}
            >
              Reconciliation Mismatches ({result.mismatches?.length || 0})
            </button>
          </div>
        </div>
      )}

      {clientGstinId && period && token && activeTab === "workbench" ? (
        <Gstr1aWorkbench
          clientGstinId={clientGstinId}
          gstin={gstin}
          period={period}
          token={token}
          backHref={backHref}
        />
      ) : result ? (
        <Gstr1aPeriodSummaryView
          result={result}
          backHref={backHref}
          token={token}
        />
      ) : (
        <div className="p-8 text-center text-xs text-gray-500">
          No reconciliation data available.
        </div>
      )}
    </div>
  );
}

export default function Gstr1aPeriodSummaryPage() {
  return (
    <Suspense
      fallback={
        <div className="flex min-h-[40vh] items-center justify-center px-8 text-[13px] text-gray-500">
          Loading GSTR-1A summary…
        </div>
      }
    >
      <Gstr1aSummaryContent />
    </Suspense>
  );
}
