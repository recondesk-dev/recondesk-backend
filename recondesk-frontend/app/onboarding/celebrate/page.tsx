"use client";

import Link from "next/link";
import { useSearchParams } from "next/navigation";
import { Suspense, useEffect, useRef, useState } from "react";
import useSWR from "swr";

import { isApiError, reconcileRunsApi, usersApi, type ReconcileRunSummaryDto } from "@/lib/api";
import { formatINR } from "@/lib/format";
import { setOnboardingDoneCookie } from "@/lib/onboarding-cookie";
import { createClient, subscribeAccessToken } from "@/lib/supabase/client";

const API_URL = process.env.NEXT_PUBLIC_API_URL ?? "https://api.recondesk.in";

function CelebrateContent() {
  const searchParams = useSearchParams();
  const runId = searchParams.get("run_id")?.trim() || "";
  const [token, setToken] = useState<string | false | null>(null);
  const completedRef = useRef(false);
  const [excelBusy, setExcelBusy] = useState(false);

  useEffect(() => subscribeAccessToken(setToken), []);

  useEffect(() => {
    const t = typeof token === "string" ? token : null;
    if (!t || completedRef.current) return;
    completedRef.current = true;
    void usersApi
      .onboardingComplete(t)
      .then(async () => {
        const supabase = createClient();
        const { data } = await supabase.auth.getUser();
        if (data.user?.id) setOnboardingDoneCookie(data.user.id);
      })
      .catch(() => {
        completedRef.current = false;
      });
  }, [token]);

  const summaryKey =
    typeof token === "string" && runId
      ? ([`/api/reconcile/runs/${runId}/summary`, token] as const)
      : null;

  const { data: summary, error } = useSWR<ReconcileRunSummaryDto>(
    summaryKey,
    ([, t]) => reconcileRunsApi.runSummary(t as string, runId),
    { revalidateOnFocus: false }
  );

  const downloadExcel = async () => {
    if (typeof token !== "string" || !runId) return;
    setExcelBusy(true);
    try {
      const res = await fetch(
        `${API_URL}/api/reconcile/runs/${encodeURIComponent(runId)}/export/excel`,
        { headers: { Authorization: `Bearer ${token}` } }
      );
      if (!res.ok) throw new Error("failed");
      const blob = await res.blob();
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = "ReconDesk-report.xlsx";
      document.body.appendChild(a);
      a.click();
      a.remove();
      URL.revokeObjectURL(url);
    } catch {
      window.alert("Could not download Excel report.");
    } finally {
      setExcelBusy(false);
    }
  };

  if (!runId) {
    return (
      <div className="mx-auto max-w-md px-6 py-20 text-center text-sm text-gray-600">
        Missing run reference. Open this page from your reconciliation results link.
      </div>
    );
  }

  const loadErr = error && isApiError(error) ? error.detail : null;

  return (
    <div className="recondesk-textured-bg min-h-screen px-6 py-16">
      <div className="mx-auto max-w-2xl text-center">
        <div className="animate-recondesk-celebrate-pop mx-auto flex h-24 w-24 items-center justify-center rounded-full bg-emerald-500 shadow-lg">
          <svg width="48" height="48" viewBox="0 0 24 24" fill="none" aria-hidden>
            <path
              d="M5 13l4 4L19 7"
              stroke="white"
              strokeWidth="2.5"
              strokeLinecap="round"
              strokeLinejoin="round"
            />
          </svg>
        </div>

        <h1 className="mt-8 text-2xl font-semibold text-gray-900">
          Your first reconciliation is complete! 🎉
        </h1>

        {loadErr && <p className="mt-4 text-sm text-red-600">{loadErr}</p>}

        {!summary && !loadErr && (
          <p className="mt-6 text-sm text-gray-500">Loading summary…</p>
        )}

        {summary && (
          <div className="mt-10 grid gap-4 sm:grid-cols-3">
            <div className="rounded-xl border border-gray-200 bg-white p-5 shadow-sm">
              <p className="text-xs font-medium text-gray-500">Matched records</p>
              <p className="mt-2 text-2xl font-semibold tabular-nums text-gray-900">
                {summary.matched_count}
              </p>
            </div>
            <div className="rounded-xl border border-gray-200 bg-white p-5 shadow-sm">
              <p className="text-xs font-medium text-gray-500">Missed ITC</p>
              <p className="mt-2 text-2xl font-semibold tabular-nums text-emerald-600">
                {summary.missed_itc_count}
              </p>
              <p className="mt-1 text-xs text-gray-500">
                {formatINR(summary.missed_itc_total_amount ?? 0)}
              </p>
            </div>
            <div className="rounded-xl border border-gray-200 bg-white p-5 shadow-sm">
              <p className="text-xs font-medium text-gray-500">Compliance risk</p>
              <p className="mt-2 text-2xl font-semibold tabular-nums text-red-600">
                {summary.wrongful_risk_count}
              </p>
              <p className="mt-1 text-xs text-gray-500">
                {formatINR(summary.wrongful_risk_total_amount ?? 0)}
              </p>
            </div>
          </div>
        )}

        <div className="mt-10 flex flex-col gap-3 sm:flex-row sm:justify-center">
          <button
            type="button"
            disabled={excelBusy || !summary}
            onClick={() => void downloadExcel()}
            className="inline-flex h-12 min-w-[200px] items-center justify-center rounded-full bg-violet-600 px-6 text-sm font-semibold text-white hover:bg-violet-700 disabled:cursor-not-allowed disabled:opacity-50"
          >
            {excelBusy ? "Preparing…" : "Download your report"}
          </button>
          <Link
            href="/dashboard"
            className="inline-flex h-12 min-w-[200px] items-center justify-center rounded-full border border-gray-300 bg-white px-6 text-sm font-semibold text-gray-800 hover:bg-gray-50"
          >
            Go to dashboard
          </Link>
        </div>
      </div>
    </div>
  );
}

export default function CelebrateOnboardingPage() {
  return (
    <Suspense
      fallback={
        <div className="recondesk-textured-bg flex min-h-screen items-center justify-center text-sm text-gray-500">
          Loading…
        </div>
      }
    >
      <CelebrateContent />
    </Suspense>
  );
}
