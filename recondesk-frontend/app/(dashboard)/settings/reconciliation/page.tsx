"use client";

import Link from "next/link";
import { useCallback, useEffect, useState } from "react";
import useSWR, { mutate } from "swr";
import { ArrowLeft, Loader2, SlidersHorizontal } from "lucide-react";

import { useToast } from "@/components/providers/ToastProvider";
import { useAccessToken } from "@/lib/hooks/useAccessToken";
import {
  AUTH_PROFILE_SWR_OPTIONS,
  authProfileFetcher,
} from "@/lib/auth-profile";
import { isApiError, reconcileSettingsApi } from "@/lib/api";

const DEFAULT_THRESHOLD = 95;

export default function ReconciliationSettingsPage() {
  const token = useAccessToken();
  const toast = useToast();
  const authToken = typeof token === "string" && token.length > 0 ? token : null;
  const resolvingToken = token === null;

  const meKey = authToken ? (["settings-me-recon", authToken] as const) : null;
  const { data: me, isLoading: meLoading } = useSWR(
    meKey,
    ([, t]) => authProfileFetcher(t),
    AUTH_PROFILE_SWR_OPTIONS
  );

  const [threshold, setThreshold] = useState(DEFAULT_THRESHOLD);
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    if (me?.auto_approve_confidence_threshold != null) {
      setThreshold(me.auto_approve_confidence_threshold);
    }
  }, [me?.auto_approve_confidence_threshold]);

  const save = useCallback(async () => {
    if (!authToken) return;
    const clamped = Math.max(0, Math.min(100, Math.round(threshold)));
    setSaving(true);
    try {
      await reconcileSettingsApi.updateAutoApproveThreshold(authToken, clamped);
      toast("Auto-approve threshold saved", "success");
      if (meKey) mutate(meKey);
      mutate(["settings-me", authToken]);
    } catch (err) {
      toast(
        isApiError(err) ? err.detail : "Failed to save threshold",
        "error"
      );
    } finally {
      setSaving(false);
    }
  }, [authToken, threshold, toast, meKey]);

  const loading = resolvingToken || (!!authToken && meLoading);
  const isAdmin = (me?.role || "").toLowerCase() === "admin";

  return (
    <div className="max-w-3xl space-y-6">
      <div className="flex items-center gap-4">
        <Link
          href="/settings"
          className="inline-flex h-10 w-10 items-center justify-center rounded-full bg-white text-gray-500 shadow-[var(--shadow-soft)] transition hover:text-[var(--ink)]"
        >
          <ArrowLeft className="h-4 w-4" />
        </Link>
        <div>
          <h1 className="text-2xl font-semibold tracking-tight text-[var(--ink)]">
            Reconciliation
          </h1>
          <p className="text-sm text-gray-500">
            Auto-triage high-confidence matches out of Review Required.
          </p>
        </div>
      </div>

      <div className="dashboard-card overflow-hidden p-5 md:p-6">
        {loading ? (
          <div className="flex flex-col items-center justify-center py-12 text-gray-500">
            <Loader2 className="h-8 w-8 animate-spin text-[var(--ink)]" />
            <span className="mt-2 text-sm">Loading…</span>
          </div>
        ) : (
          <div className="space-y-5">
            <div className="flex items-start gap-3">
              <div className="inline-flex h-10 w-10 shrink-0 items-center justify-center rounded-full bg-[#F3F4F6]">
                <SlidersHorizontal className="h-5 w-5 text-gray-700" />
              </div>
              <div>
                <h2 className="text-base font-semibold text-[var(--ink)]">
                  Confidence auto-approve threshold
                </h2>
                <p className="mt-1 text-sm text-gray-500">
                  At the end of each reconciliation run, any Review Required pair
                  with a matcher confidence score at or above this threshold is
                  tagged <span className="font-medium text-gray-700">Auto-Approved</span>{" "}
                  and counted under Matched (not a separate tab). Default is 95%.
                  Applies on the next run after you save.
                </p>
              </div>
            </div>

            <div className="space-y-3 rounded-xl border border-[#EFEFF2] bg-[#FAFAFA] p-4">
              <div className="flex items-center justify-between gap-4">
                <label
                  htmlFor="auto-approve-threshold"
                  className="text-sm font-medium text-[var(--ink)]"
                >
                  Threshold
                </label>
                <div className="flex items-center gap-2">
                  <input
                    id="auto-approve-threshold-num"
                    type="number"
                    min={0}
                    max={100}
                    disabled={!isAdmin || saving}
                    value={threshold}
                    onChange={(e) =>
                      setThreshold(
                        Math.max(0, Math.min(100, Number(e.target.value) || 0))
                      )
                    }
                    className="h-9 w-20 rounded-lg border border-[#E5E7EB] bg-white px-2 text-right text-sm font-semibold text-[var(--ink)] disabled:opacity-50"
                  />
                  <span className="text-sm text-gray-500">%</span>
                </div>
              </div>
              <input
                id="auto-approve-threshold"
                type="range"
                min={0}
                max={100}
                step={1}
                disabled={!isAdmin || saving}
                value={threshold}
                onChange={(e) => setThreshold(Number(e.target.value))}
                className="w-full accent-[var(--ink)] disabled:opacity-50"
              />
              <p className="text-xs text-gray-500">
                Example: at 95%, L2 normalized matches (95) that land in review
                are auto-approved; L3 (75) and L2 minor-diff (90) still need
                manual review unless you lower the threshold.
              </p>
            </div>

            {!isAdmin ? (
              <p className="text-sm text-amber-800">
                Only firm admins can change this setting.
              </p>
            ) : (
              <button
                type="button"
                disabled={saving}
                onClick={() => void save()}
                className="inline-flex h-10 items-center justify-center gap-2 rounded-full bg-[var(--ink)] px-5 text-sm font-semibold text-white hover:opacity-90 disabled:opacity-50"
              >
                {saving ? (
                  <Loader2 className="h-4 w-4 animate-spin" />
                ) : null}
                Save threshold
              </button>
            )}
          </div>
        )}
      </div>
    </div>
  );
}
