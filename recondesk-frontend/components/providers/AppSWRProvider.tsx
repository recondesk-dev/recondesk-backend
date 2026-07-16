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

export function AppSWRProvider({ children }: { children: ReactNode }) {
  const toast = useToast();
  const [connectionLost, setConnectionLost] = useState(false);
  const redirect401Ref = useRef(false);
  const lastServerErrorToastRef = useRef(0);

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
        setConnectionLost(true);
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
    [toast]
  );

  const onSuccess = useCallback(() => {
    setConnectionLost(false);
  }, []);

  useEffect(() => {
    const onOnline = () => setConnectionLost(false);
    const onOffline = () => setConnectionLost(true);
    window.addEventListener("online", onOnline);
    window.addEventListener("offline", onOffline);
    return () => {
      window.removeEventListener("online", onOnline);
      window.removeEventListener("offline", onOffline);
    };
  }, []);

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
            Connection lost — please check your internet
          </span>
          <button
            type="button"
            aria-label="Dismiss"
            className="inline-flex min-h-[44px] shrink-0 items-center justify-center rounded-full px-3 text-xs font-semibold text-amber-900 underline hover:bg-amber-100"
            onClick={() => setConnectionLost(false)}
          >
            Dismiss
          </button>
        </div>
      )}
      {children}
    </SWRConfig>
  );
}
