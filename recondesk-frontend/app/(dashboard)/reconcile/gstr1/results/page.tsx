"use client";

import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { Suspense, useEffect, useState } from "react";

import { Gstr1ResultsView } from "@/components/reconcile/Gstr1ResultsView";
import {
  loadGstr1Result,
  loadGstr1ResultByRunId,
  type Gstr1ReconcileResult,
} from "@/lib/gstr1Reconcile";
import { useAccessToken } from "@/lib/hooks/useAccessToken";

function Gstr1ReconcileResultsContent() {
  const router = useRouter();
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
      // Prefer persisted run when run_id is present (survives new sessions).
      if (runId && token) {
        const fromDb = await loadGstr1ResultByRunId(token, runId);
        if (!cancelled) {
          setResult(fromDb ?? loadGstr1Result());
        }
        return;
      }
      // Fast-path fallback: session storage from the just-completed upload.
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
        <p className="text-[13px] text-gray-500">Loading results…</p>
      </div>
    );
  }

  if (!result) {
    return (
      <div className="mx-auto flex min-h-[50vh] w-full max-w-lg flex-col items-center justify-center px-8 text-center">
        <h1 className="text-xl font-semibold tracking-tight text-[var(--ink)]">
          No GSTR-1 results yet
        </h1>
        <p className="mt-2 text-[14px] text-gray-500">
          Run a Sales Reconciliation to see matched invoices, mismatches, and
          the GSTR-1 vs 3B tie-out.
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

  const runAgainHref = result.client_gstin_id
    ? `/reconcile/gstr1/new?client_gstin_id=${encodeURIComponent(result.client_gstin_id)}`
    : "/reconcile/gstr1/new";

  return (
    <Gstr1ResultsView
      result={result}
      onRunAgain={() => router.push(runAgainHref)}
      authToken={token}
      runId={runId ?? result.run_id ?? null}
    />
  );
}

export default function Gstr1ReconcileResultsPage() {
  return (
    <Suspense
      fallback={
        <div className="flex min-h-[40vh] items-center justify-center px-8 text-[13px] text-gray-500">
          Loading results…
        </div>
      }
    >
      <Gstr1ReconcileResultsContent />
    </Suspense>
  );
}
