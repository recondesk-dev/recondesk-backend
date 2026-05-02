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

function isLikelyNetworkError(err: unknown): boolean {
  if (typeof TypeError !== "undefined" && err instanceof TypeError) return true;
  const msg =
    err && typeof err === "object" && "message" in err
      ? String((err as { message: unknown }).message)
      : err instanceof Error
        ? err.message
        : "";
  return /failed to fetch|network|load failed|aborted|internet/i.test(msg);
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

      if (status === 503 || isLikelyNetworkError(err)) {
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

  useEffect(() => {
    const onOnline = () => setConnectionLost(false);
    window.addEventListener("online", onOnline);
    return () => window.removeEventListener("online", onOnline);
  }, []);

  return (
    <SWRConfig
      value={{
        revalidateOnFocus: false,
        dedupingInterval: 30_000,
        onError,
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
            className="inline-flex min-h-[44px] shrink-0 items-center justify-center rounded-lg px-3 text-xs font-semibold text-amber-900 underline hover:bg-amber-100"
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
