"use client";

import { useEffect, useRef, useState } from "react";
import { useSWRConfig } from "swr";
import { useToast } from "@/components/providers/ToastProvider";
import {
  getTrackedBackgroundRuns,
  untrackBackgroundRun,
  showDesktopNotification,
  type TrackedBackgroundRun,
} from "@/lib/desktopNotification";
import { importWizardApi } from "@/lib/api";
import { subscribeAccessToken } from "@/lib/supabase/client";

const POLL_INTERVAL_MS = 4000;

export function BackgroundRunNotifier() {
  const [accessToken, setAccessToken] = useState<string | false | null>(null);
  const [trackedRuns, setTrackedRuns] = useState<TrackedBackgroundRun[]>([]);
  const { mutate } = useSWRConfig();
  const toast = useToast();
  const inFlightRef = useRef<Set<string>>(new Set());

  // Listen for access token
  useEffect(() => subscribeAccessToken(setAccessToken), []);

  // Sync tracked runs from storage & events
  useEffect(() => {
    const refreshRuns = () => {
      setTrackedRuns(getTrackedBackgroundRuns());
    };
    refreshRuns();

    window.addEventListener("recondesk:tracked_runs_updated", refreshRuns);
    window.addEventListener("storage", refreshRuns);
    return () => {
      window.removeEventListener("recondesk:tracked_runs_updated", refreshRuns);
      window.removeEventListener("storage", refreshRuns);
    };
  }, []);

  // Poll active background runs
  useEffect(() => {
    if (typeof accessToken !== "string" || !accessToken || trackedRuns.length === 0) {
      return;
    }

    let cancelled = false;
    let timer: ReturnType<typeof setTimeout> | undefined;

    const checkRuns = async () => {
      if (cancelled) return;

      const runs = getTrackedBackgroundRuns();
      if (runs.length === 0) {
        setTrackedRuns([]);
        return;
      }

      await Promise.all(
        runs.map(async (run) => {
          if (inFlightRef.current.has(run.runId)) return;
          inFlightRef.current.add(run.runId);

          try {
            const status = await importWizardApi.pollStatus(accessToken, run.runId);
            if (cancelled) return;

            if (status.status === "complete") {
              untrackBackgroundRun(run.runId);
              inFlightRef.current.delete(run.runId);

              const clientLabel = run.clientName || "Client";
              const periodText = run.periodLabel ? ` (${run.periodLabel})` : "";
              const resultsUrl = `/reconcile/runs/${run.runId}/results`;

              // Trigger native browser notification
              showDesktopNotification("Reconciliation Ready! 🎉", {
                body: `${clientLabel}${periodText} reconciliation is complete. Click to view results.`,
                onClickUrl: resultsUrl,
                tag: `recon-ready-${run.runId}`,
              });

              // Trigger in-app toast
              toast(`Reconciliation complete for ${clientLabel}.`, "success");

              // Refresh reconciliation queries in the current view
              void mutate((key: unknown) => {
                if (typeof key === "string") {
                  return (
                    key.includes("/api/reconcile/runs") ||
                    key.includes("/api/dashboard") ||
                    key.includes("/api/runs")
                  );
                }
                return false;
              });
            } else if (status.status === "failed" || status.status === "error") {
              untrackBackgroundRun(run.runId);
              inFlightRef.current.delete(run.runId);

              const clientLabel = run.clientName || "Client";

              showDesktopNotification("Reconciliation Encountered an Issue", {
                body: `Reconciliation for ${clientLabel} failed. Click to view details.`,
                onClickUrl: "/reconciliations",
                tag: `recon-failed-${run.runId}`,
              });

              toast(`Reconciliation failed for ${clientLabel}.`, "error");

              void mutate((key: unknown) => {
                if (typeof key === "string") {
                  return (
                    key.includes("/api/reconcile/runs") ||
                    key.includes("/api/dashboard") ||
                    key.includes("/api/runs")
                  );
                }
                return false;
              });
            }
          } catch {
            // Transient network failure: keep polling
          } finally {
            inFlightRef.current.delete(run.runId);
          }
        })
      );

      if (!cancelled) {
        setTrackedRuns(getTrackedBackgroundRuns());
        timer = setTimeout(() => {
          void checkRuns();
        }, POLL_INTERVAL_MS);
      }
    };

    void checkRuns();

    return () => {
      cancelled = true;
      if (timer != null) clearTimeout(timer);
    };
  }, [accessToken, trackedRuns.length, mutate, toast]);

  return null;
}
