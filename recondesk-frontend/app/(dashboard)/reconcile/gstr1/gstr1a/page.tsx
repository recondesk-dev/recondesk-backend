"use client";

import Link from "next/link";
import { useSearchParams } from "next/navigation";
import { Suspense, useEffect, useState } from "react";

import { Gstr1aPeriodSummaryView } from "@/components/reconcile/Gstr1aPeriodSummaryView";
import {
  loadGstr1Result,
  loadGstr1ResultByRunId,
  type Gstr1ReconcileResult,
} from "@/lib/gstr1Reconcile";
import { useAccessToken } from "@/lib/hooks/useAccessToken";

function Gstr1aSummaryContent() {
  const searchParams = useSearchParams();
  const runId = searchParams.get("run_id")?.trim() || null;
  const tokenState = useAccessToken();
  const token =
    typeof tokenState === "string" && tokenState.length > 0 ? tokenState : null;

  const [result, setResult] = useState<Gstr1ReconcileResult | null | undefined>(
    undefined
  );

  useEffect(() => {
    let cancelled = false;

    async function load() {
      if (runId && token) {
        const fromDb = await loadGstr1ResultByRunId(token, runId);
        if (!cancelled) {
          setResult(fromDb ?? loadGstr1Result());
        }
        return;
      }
      if (!cancelled) {
        setResult(loadGstr1Result());
      }
    }

    void load();
    return () => {
      cancelled = true;
    };
  }, [runId, token]);

  if (result === undefined) {
    return (
      <div className="flex min-h-[40vh] items-center justify-center px-8">
        <p className="text-[13px] text-gray-500">Loading GSTR-1A summary…</p>
      </div>
    );
  }

  if (!result) {
    return (
      <div className="mx-auto flex min-h-[50vh] w-full max-w-lg flex-col items-center justify-center px-8 text-center">
        <h1 className="text-xl font-semibold tracking-tight text-[var(--ink)]">
          No GSTR-1 run loaded
        </h1>
        <p className="mt-2 text-[14px] text-gray-500">
          Open this summary from a completed GSTR-1 reconciliation result.
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

  const backHref = runId
    ? `/reconcile/gstr1/results?run_id=${encodeURIComponent(runId)}`
    : result.run_id
      ? `/reconcile/gstr1/results?run_id=${encodeURIComponent(result.run_id)}`
      : "/reconcile/gstr1/results";

  return (
    <Gstr1aPeriodSummaryView
      result={result}
      backHref={backHref}
      token={token}
    />
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
