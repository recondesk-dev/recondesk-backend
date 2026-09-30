"use client";

import { useEffect } from "react";
import * as Sentry from "@sentry/nextjs";
import Link from "next/link";
import { AlertCircle, RefreshCw } from "lucide-react";

export default function DashboardError({
  error,
  reset,
}: {
  error: Error & { digest?: string };
  reset: () => void;
}) {
  useEffect(() => {
    Sentry.captureException(error);
  }, [error]);

  return (
    <div className="flex min-h-[50vh] flex-col items-center justify-center p-8 text-center">
      <div className="mx-auto flex h-14 w-14 items-center justify-center rounded-2xl bg-red-50 text-red-600 ring-8 ring-red-50/50 mb-4">
        <AlertCircle className="h-7 w-7" />
      </div>
      <h2 className="text-xl font-semibold tracking-tight text-[var(--ink)]">
        Something went wrong
      </h2>
      <p className="mt-2 max-w-md text-sm text-[var(--text-secondary)]">
        {error?.message && !error.message.includes("digest")
          ? error.message
          : "An unexpected error occurred while loading this page. Our team has been notified."}
      </p>
      <div className="mt-6 flex flex-wrap items-center justify-center gap-3">
        <button
          type="button"
          onClick={reset}
          className="inline-flex items-center gap-2 rounded-full bg-[var(--ink)] px-5 py-2 text-sm font-semibold text-white shadow-sm hover:opacity-90 transition-opacity"
        >
          <RefreshCw className="h-4 w-4" />
          Try again
        </button>
        <Link
          href="/dashboard"
          className="inline-flex items-center rounded-full border border-[var(--border)] bg-white px-5 py-2 text-sm font-medium text-[var(--text-primary)] hover:bg-[var(--bg)] transition-colors"
        >
          Back to Dashboard
        </Link>
      </div>
    </div>
  );
}
