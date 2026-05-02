"use client";

import type { ReactNode } from "react";
import { useCallback, useEffect, useRef, useState } from "react";
import { SWRConfig } from "swr";

type ToastItem = { id: string; message: string; type: "error" | "info" };

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
  const [toasts, setToasts] = useState<ToastItem[]>([]);
  const [connectionLost, setConnectionLost] = useState(false);
  const redirect401Ref = useRef(false);
  const lastServerErrorToastRef = useRef(0);

  const pushToast = useCallback((message: string, type: ToastItem["type"]) => {
    const id = `${Date.now()}-${Math.random().toString(36).slice(2)}`;
    setToasts((prev) => [...prev, { id, message, type }]);
    window.setTimeout(() => {
      setToasts((prev) => prev.filter((t) => t.id !== id));
    }, 4000);
  }, []);

  const dismissToast = useCallback((id: string) => {
    setToasts((prev) => prev.filter((t) => t.id !== id));
  }, []);

  const onError = useCallback(
    (err: unknown) => {
      const status = getHttpStatus(err);

      if (status === 401) {
        pushToast("Session expired — please sign in again", "error");
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
          pushToast("Something went wrong — please try again", "error");
        }
      }
    },
    [pushToast]
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
            className="shrink-0 rounded px-2 py-0.5 text-xs font-semibold text-amber-900 underline hover:bg-amber-100"
            onClick={() => setConnectionLost(false)}
          >
            Dismiss
          </button>
        </div>
      )}
      <div
        className="pointer-events-none fixed bottom-4 right-4 z-[101] flex max-w-sm flex-col gap-2"
        aria-live="polite"
      >
        <div className="pointer-events-auto flex flex-col gap-2">
          {toasts.map((t) => (
            <div
              key={t.id}
              className={`rounded-lg border px-4 py-3 text-sm shadow-lg ${
                t.type === "error"
                  ? "border-red-200 bg-red-50 text-red-900"
                  : "border-gray-200 bg-white text-gray-900"
              }`}
            >
              <div className="flex items-start justify-between gap-2">
                <p>{t.message}</p>
                <button
                  type="button"
                  className="shrink-0 text-xs font-medium opacity-70 hover:opacity-100"
                  onClick={() => dismissToast(t.id)}
                >
                  ×
                </button>
              </div>
            </div>
          ))}
        </div>
      </div>
      {children}
    </SWRConfig>
  );
}
