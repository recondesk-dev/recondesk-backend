"use client";

import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { Suspense, useEffect, useState } from "react";

import { Gstr1ResultsView } from "@/components/reconcile/Gstr1ResultsView";
import {
  loadGstr1Result,
  loadGstr1ResultByRunId,
  loadGstr1RunId,
  type Gstr1ReconcileResult,
} from "@/lib/gstr1Reconcile";
import { useAccessToken } from "@/lib/hooks/useAccessToken";

function Gstr1ReconcileResultsContent() {
  const router = useRouter();
  const searchParams = useSearchParams();
  const queryRunId = searchParams.get("run_id")?.trim() || null;
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

      // In-memory result from current session upload has priority when no explicit URL param is set.
      if (!queryRunId && mem) {
        if (!cancelled) {
          setResult(mem);
          setResolvedRunId(mem.run_id ? String(mem.run_id) : null);
        }
        return;
      }

      const runId = queryRunId || (mem?.run_id ? String(mem.run_id) : null) || loadGstr1RunId();
      if (!cancelled) setResolvedRunId(runId);

      // Persisted runs: wait for auth, then fetch from the backend.
      if (runId) {
        if (tokenPending) return;
        if (!token) {
          if (!cancelled) setResult(null);
          return;
        }
        // Same-tab upload already has the payload — show it while GET runs.
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

      // Ad-hoc run without client_gstin_id / run_id: in-memory only.
      if (!cancelled) {
        setResult(mem);
      }
    }

    void load();
    return () => {
      cancelled = true;
    };
  }, [queryRunId, token, tokenPending]);

  if (result === undefined || (queryRunId && tokenPending)) {
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
      runId={result.run_id ?? resolvedRunId ?? null}
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
