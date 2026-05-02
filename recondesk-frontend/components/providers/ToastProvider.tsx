"use client";

import {
  createContext,
  useCallback,
  useContext,
  useState,
  type ReactNode,
} from "react";

export type ToastVariant = "error" | "info" | "success";

type ToastItem = { id: string; message: string; type: ToastVariant };

type ToastContextValue = {
  toast: (message: string, type?: ToastVariant) => void;
};

const ToastContext = createContext<ToastContextValue | null>(null);

export function useToast(): ToastContextValue["toast"] {
  const ctx = useContext(ToastContext);
  if (!ctx) {
    throw new Error("useToast must be used within ToastProvider");
  }
  return ctx.toast;
}

export function ToastProvider({ children }: { children: ReactNode }) {
  const [toasts, setToasts] = useState<ToastItem[]>([]);

  const toast = useCallback((message: string, type: ToastVariant = "info") => {
    const id = `${Date.now()}-${Math.random().toString(36).slice(2)}`;
    setToasts((prev) => [...prev, { id, message, type }]);
    window.setTimeout(() => {
      setToasts((prev) => prev.filter((t) => t.id !== id));
    }, 4200);
  }, []);

  const dismissToast = useCallback((id: string) => {
    setToasts((prev) => prev.filter((t) => t.id !== id));
  }, []);

  return (
    <ToastContext.Provider value={{ toast }}>
      {children}
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
                  : t.type === "success"
                    ? "border-emerald-200 bg-emerald-50 text-emerald-950"
                    : "border-gray-200 bg-white text-gray-900"
              }`}
            >
              <div className="flex min-h-[44px] items-start justify-between gap-2">
                <p className="pt-2">{t.message}</p>
                <button
                  type="button"
                  aria-label="Dismiss"
                  className="inline-flex min-h-[44px] min-w-[44px] shrink-0 items-center justify-center rounded-lg text-xs font-medium opacity-70 hover:bg-black/5 hover:opacity-100"
                  onClick={() => dismissToast(t.id)}
                >
                  ×
                </button>
              </div>
            </div>
          ))}
        </div>
      </div>
    </ToastContext.Provider>
  );
}
