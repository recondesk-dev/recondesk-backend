"use client";

import type { Gstr1aWindow } from "@/lib/gstr1Reconcile";

/** Compact pill for eligible mismatches (countdown or closed). */
export function Gstr1aWindowBadge({
  eligibility,
  window,
}: {
  eligibility?: string | null;
  window?: Gstr1aWindow | null;
}) {
  if (!window) return null;
  const elig = String(eligibility || "").toLowerCase();
  if (elig !== "eligible") return null;

  if (window.status === "window_closed") {
    return (
      <span className="inline-flex rounded-full bg-[#F0F0F0] px-2.5 py-0.5 text-[11px] font-medium text-gray-600">
        GSTR-1A window closed
      </span>
    );
  }

  const days = window.days_remaining;
  if (days == null || Number.isNaN(days)) return null;

  const tone =
    days < 3
      ? "bg-red-50 text-red-700"
      : days < 7
        ? "bg-amber-50 text-amber-800"
        : "bg-[#F0F0F0] text-gray-600";

  const label =
    days < 0
      ? "GSTR-1A window expired"
      : days === 1
        ? "1 day left for GSTR-1A"
        : `${days} days left for GSTR-1A`;

  return (
    <span
      className={`inline-flex rounded-full px-2.5 py-0.5 text-[11px] font-medium ${tone}`}
    >
      {label}
    </span>
  );
}

/** Prominent period-level countdown banner for the GSTR-1A summary screen. */
export function Gstr1aWindowBanner({
  window,
}: {
  window?: Gstr1aWindow | null;
}) {
  if (!window) {
    return (
      <div className="rounded-[1.25rem] bg-[#F7F7F8] px-5 py-4">
        <p className="text-[11px] font-medium uppercase tracking-widest text-gray-400">
          GSTR-1A amendment window
        </p>
        <p className="mt-1 text-[15px] font-semibold text-[var(--ink)]">
          Window not available
        </p>
        <p className="mt-1 text-[13px] text-gray-500">
          Provide GSTR-1 / GSTR-3B filed dates on the run to compute days
          remaining.
        </p>
      </div>
    );
  }

  if (window.status === "window_closed") {
    return (
      <div className="rounded-[1.25rem] bg-[#F0F0F0] px-5 py-4 ring-1 ring-[#E5E5E5]">
        <p className="text-[11px] font-medium uppercase tracking-widest text-gray-400">
          GSTR-1A amendment window
        </p>
        <p className="mt-1 text-[18px] font-semibold tracking-tight text-gray-700">
          GSTR-1A window closed
        </p>
        <p className="mt-1 text-[13px] text-gray-500">
          {window.note || "GSTR-3B already filed for this period."}
        </p>
      </div>
    );
  }

  const days = window.days_remaining;
  const tone =
    days == null
      ? "bg-[#F7F7F8] text-[var(--ink)] ring-[#E5E5E5]"
      : days < 3
        ? "bg-red-50 text-red-800 ring-red-200"
        : days < 7
          ? "bg-amber-50 text-amber-900 ring-amber-200"
          : "bg-[#F7F7F8] text-[var(--ink)] ring-[#E5E5E5]";

  const headline =
    days == null
      ? "Window status unknown"
      : days < 0
        ? "GSTR-1A window expired"
        : days === 1
          ? "1 day left for GSTR-1A"
          : `${days} days left for GSTR-1A`;

  return (
    <div className={`rounded-[1.25rem] px-5 py-4 ring-1 ${tone}`}>
      <p className="text-[11px] font-medium uppercase tracking-widest opacity-70">
        GSTR-1A amendment window
      </p>
      <p className="mt-1 text-[18px] font-semibold tracking-tight tabular-nums">
        {headline}
      </p>
      <p className="mt-1 text-[13px] opacity-80">
        {window.gstr3b_due_date
          ? `GSTR-3B due ${window.gstr3b_due_date}`
          : window.note ||
            "Amend eligible invoices via GSTR-1A before GSTR-3B is filed."}
      </p>
    </div>
  );
}
