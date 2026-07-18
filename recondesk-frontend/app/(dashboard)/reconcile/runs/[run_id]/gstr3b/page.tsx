"use client";

import { ArrowLeft } from "lucide-react";
import Link from "next/link";
import { useParams } from "next/navigation";

import { Gstr3bSummaryView } from "@/components/reconcile/Gstr3bSummaryView";
import { useAccessToken } from "@/lib/hooks/useAccessToken";

export default function Gstr3bSummaryPage() {
  const params = useParams();
  const runId = typeof params.run_id === "string" ? params.run_id : "";
  const tokenState = useAccessToken();
  const authToken =
    typeof tokenState === "string" && tokenState.length > 0 ? tokenState : null;
  const authReady = Boolean(authToken);
  const sessionMissing = tokenState === false;

  return (
    <div className="mx-auto max-w-5xl px-4 py-6 sm:px-6">
      <div className="mb-5">
        <Link
          href={
            runId
              ? `/reconcile/runs/${encodeURIComponent(runId)}/results`
              : "/dashboard"
          }
          className="inline-flex items-center gap-1.5 text-[13px] font-medium text-gray-500 hover:text-gray-800"
        >
          <ArrowLeft className="h-3.5 w-3.5" />
          Back to results
        </Link>
        <h1 className="mt-3 text-xl font-semibold tracking-tight text-gray-900">
          GSTR-3B summary
        </h1>
        <p className="mt-1 text-[13px] text-gray-500">
          Filed return figures, ITC vs GSTR-2B, and Rule 88D / DRC-01C threshold.
        </p>
      </div>

      {tokenState === null && (
        <p className="text-[13px] text-gray-400">Checking session…</p>
      )}

      {sessionMissing && (
        <p className="text-[13px] text-red-500">
          Sign in to view GSTR-3B for this run.
        </p>
      )}

      {authReady && runId && authToken && (
        <div className="rounded-2xl border border-[#E5E7EB] bg-white p-5 sm:p-6">
          <Gstr3bSummaryView
            runId={runId}
            authToken={authToken}
            variant="page"
          />
        </div>
      )}

      {authReady && !runId && (
        <p className="text-[13px] text-red-500">Missing run id.</p>
      )}
    </div>
  );
}
