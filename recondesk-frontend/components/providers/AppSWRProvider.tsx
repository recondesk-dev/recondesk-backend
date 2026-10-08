"use client";

import type { ReactNode } from "react";
import { useCallback, useEffect, useRef, useState } from "react";
import { SWRConfig } from "swr";

import { useToast } from "@/components/providers/ToastProvider";

function getHttpStatus(err: unknown): number | null {
  if (err && typeof err === "object" && "status" in err) {
    const s = (err as { status: unknown }).status;
    if (typeof s === "number") return s;
  }
  return null;
}

function errorMessage(err: unknown): string {
  if (err && typeof err === "object" && "message" in err) {
    return String((err as { message: unknown }).message ?? "");
  }
  if (err instanceof Error) return err.message;
  if (err && typeof err === "object" && "detail" in err) {
    return String((err as { detail: unknown }).detail ?? "");
  }
  return typeof err === "string" ? err : "";
}

/** Timeouts / navigation cancels — not an internet outage. */
function isAbortOrTimeout(err: unknown): boolean {
  const status = getHttpStatus(err);
  if (status === 408) return true;
  if (err && typeof err === "object" && "name" in err) {
    const name = String((err as { name: unknown }).name ?? "");
    if (name === "AbortError" || name === "TimeoutError") return true;
  }
  return /aborted|abort(ed)?|timed?\s*out|timeout/i.test(errorMessage(err));
}

/**
 * True only for real transport failures (offline / DNS / CORS / unreachable host).
 * Do NOT treat every TypeError or 503 as "no internet".
 */
function isLikelyNetworkError(err: unknown): boolean {
  if (isAbortOrTimeout(err)) return false;

  if (typeof navigator !== "undefined" && navigator.onLine === false) {
    return true;
  }

  if (typeof DOMException !== "undefined" && err instanceof DOMException) {
    if (err.name === "NetworkError") return true;
  }

  const msg = errorMessage(err);
  return /failed to fetch|load failed|networkerror|network request failed|err_network|err_internet_disconnected|err_connection/i.test(
    msg
  );
}

/** Lightweight probe to verify if ReconDesk / internet is genuinely reachable. */
async function probeConnectivity(): Promise<boolean> {
  if (typeof navigator !== "undefined" && navigator.onLine === false) {
    return false;
  }
  try {
    const controller = new AbortController();
    const timer = setTimeout(() => controller.abort(), 3500);
    const res = await fetch("/api/keepalive", {
      method: "GET",
      cache: "no-store",
      signal: controller.signal,
    });
    clearTimeout(timer);
    if (!res.ok) return false;
    const data = (await res.json()) as { ok?: boolean; backend?: boolean };
    return Boolean(data.ok && data.backend !== false);
  } catch {
    return false;
  }
}

/** How long to wait after a success before hiding the banner (avoids flicker). */
const CLEAR_BANNER_AFTER_MS = 800;
/** Require this many network failures in the window before probing/showing banner. */
const NETWORK_ERROR_THRESHOLD = 3;
const NETWORK_ERROR_WINDOW_MS = 10_000;
/** Browser `offline` events are often spurious — confirm after this delay. */
const OFFLINE_CONFIRM_MS = 2_000;

export function AppSWRProvider({ children }: { children: ReactNode }) {
  const toast = useToast();
  const [connectionLost, setConnectionLost] = useState(false);
  const [isDeviceOffline, setIsDeviceOffline] = useState(false);
  const redirect401Ref = useRef(false);
  const lastServerErrorToastRef = useRef(0);
  const clearBannerTimerRef = useRef<number | null>(null);
  const offlineConfirmTimerRef = useRef<number | null>(null);
  const connectionLostRef = useRef(false);
  const networkErrorTimesRef = useRef<number[]>([]);

  const cancelClearTimer = useCallback(() => {
    if (clearBannerTimerRef.current != null) {
      window.clearTimeout(clearBannerTimerRef.current);
      clearBannerTimerRef.current = null;
    }
  }, []);

  const cancelOfflineConfirm = useCallback(() => {
    if (offlineConfirmTimerRef.current != null) {
      window.clearTimeout(offlineConfirmTimerRef.current);
      offlineConfirmTimerRef.current = null;
    }
  }, []);

  const showConnectionLost = useCallback((deviceOffline = false) => {
    cancelClearTimer();
    connectionLostRef.current = true;
    setIsDeviceOffline(deviceOffline);
    setConnectionLost(true);
  }, [cancelClearTimer]);

  const hideConnectionLost = useCallback(() => {
    cancelClearTimer();
    cancelOfflineConfirm();
    networkErrorTimesRef.current = [];
    connectionLostRef.current = false;
    setConnectionLost(false);
  }, [cancelClearTimer, cancelOfflineConfirm]);

  const scheduleClearConnectionLost = useCallback(() => {
    if (!connectionLostRef.current) return;
    cancelClearTimer();
    clearBannerTimerRef.current = window.setTimeout(() => {
      clearBannerTimerRef.current = null;
      networkErrorTimesRef.current = [];
      connectionLostRef.current = false;
      setConnectionLost(false);
    }, CLEAR_BANNER_AFTER_MS);
  }, [cancelClearTimer]);

  const noteNetworkFailure = useCallback(async () => {
    const now = Date.now();
    const recent = networkErrorTimesRef.current.filter(
      (t) => now - t < NETWORK_ERROR_WINDOW_MS
    );
    recent.push(now);
    networkErrorTimesRef.current = recent;
    if (recent.length >= NETWORK_ERROR_THRESHOLD) {
      // Before showing the banner, verify whether ReconDesk is actually reachable.
      // If the probe succeeds, this was a transient or endpoint-specific error, NOT a connectivity loss.
      if (typeof navigator !== "undefined" && navigator.onLine) {
        const isReachable = await probeConnectivity();
        if (isReachable) {
          networkErrorTimesRef.current = [];
          return;
        }
      }
      showConnectionLost(typeof navigator !== "undefined" && !navigator.onLine);
    }
  }, [showConnectionLost]);

  const onError = useCallback(
    (err: unknown) => {
      const status = getHttpStatus(err);

      if (status === 401) {
        toast("Session expired — please sign in again", "error");
        if (!redirect401Ref.current) {
          redirect401Ref.current = true;
          window.setTimeout(() => {
            window.location.assign("/login");
          }, 1200);
        }
        return;
      }

      // Aborts / client timeouts / Railway cold-start 503s are not "no internet".
      if (isAbortOrTimeout(err) || status === 503 || status === 502 || status === 504) {
        return;
      }

      if (isLikelyNetworkError(err)) {
        // Already offline according to the browser — show immediately.
        if (typeof navigator !== "undefined" && navigator.onLine === false) {
          showConnectionLost(true);
          return;
        }
        void noteNetworkFailure();
        return;
      }

      if (status === 500) {
        const now = Date.now();
        if (now - lastServerErrorToastRef.current > 2500) {
          lastServerErrorToastRef.current = now;
          toast("Something went wrong — please try again", "error");
        }
      }
    },
    [noteNetworkFailure, showConnectionLost, toast]
  );

  const onSuccess = useCallback(() => {
    networkErrorTimesRef.current = [];
    scheduleClearConnectionLost();
  }, [scheduleClearConnectionLost]);

  // Active recovery polling & re-checks when connectionLost is true
  useEffect(() => {
    if (!connectionLost) return;

    let cancelled = false;
    const checkRecovery = async () => {
      if (cancelled) return;
      if (typeof navigator !== "undefined" && navigator.onLine === false) {
        setIsDeviceOffline(true);
        return;
      }
      const reachable = await probeConnectivity();
      if (!cancelled && reachable) {
        hideConnectionLost();
      }
    };

    // Poll every 3 seconds while banner is showing
    const pollId = window.setInterval(() => {
      void checkRecovery();
    }, 3000);

    const onOnline = () => {
      void checkRecovery();
    };
    const onFocus = () => {
      void checkRecovery();
    };
    const onVisibility = () => {
      if (document.visibilityState === "visible") {
        void checkRecovery();
      }
    };

    window.addEventListener("online", onOnline);
    window.addEventListener("focus", onFocus);
    document.addEventListener("visibilitychange", onVisibility);

    return () => {
      cancelled = true;
      window.clearInterval(pollId);
      window.removeEventListener("online", onOnline);
      window.removeEventListener("focus", onFocus);
      document.removeEventListener("visibilitychange", onVisibility);
    };
  }, [connectionLost, hideConnectionLost]);

  // Listen to offline event with debounce & probe verification
  useEffect(() => {
    const onOffline = () => {
      // macOS/Chrome often fires a brief spurious `offline` — confirm first.
      cancelOfflineConfirm();
      offlineConfirmTimerRef.current = window.setTimeout(async () => {
        offlineConfirmTimerRef.current = null;
        if (typeof navigator !== "undefined" && navigator.onLine === false) {
          showConnectionLost(true);
        } else {
          const reachable = await probeConnectivity();
          if (!reachable) {
            showConnectionLost(false);
          }
        }
      }, OFFLINE_CONFIRM_MS);
    };
    window.addEventListener("offline", onOffline);
    return () => {
      window.removeEventListener("offline", onOffline);
      cancelClearTimer();
      cancelOfflineConfirm();
    };
  }, [
    cancelClearTimer,
    cancelOfflineConfirm,
    showConnectionLost,
  ]);

  return (
    <SWRConfig
      value={{
        revalidateOnFocus: false,
        dedupingInterval: 30_000,
        onError,
        onSuccess,
      }}
    >
      {connectionLost && (
        <div
          role="alert"
          className="fixed inset-x-0 top-0 z-[100] flex items-center justify-center border-b border-amber-300 bg-amber-50 px-4 py-2 text-center text-sm text-amber-950 shadow-sm"
        >
          <span className="flex-1 pr-2">
            {isDeviceOffline
              ? "No internet connection detected — check your connection"
              : "Can't reach ReconDesk — reconnecting..."}
          </span>
          <button
            type="button"
            aria-label="Dismiss"
            className="inline-flex min-h-[44px] shrink-0 items-center justify-center rounded-full px-3 text-xs font-semibold text-amber-900 underline hover:bg-amber-100"
            onClick={() => hideConnectionLost()}
          >
            Dismiss
          </button>
        </div>
      )}
      {children}
    </SWRConfig>
  );
}
