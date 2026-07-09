export function StatCard({
  label,
  value,
  hint,
  empty = false,
  emptyCaption,
  emptyIcon = "dash",
}: {
  label: string;
  value: React.ReactNode;
  /** Shown on the info icon tooltip (replaces decorative corner icons). */
  hint?: string;
  empty?: boolean;
  emptyCaption?: string;
  /** Visual for empty state: dash (default) or a calm success check/shield. */
  emptyIcon?: "dash" | "check";
}) {
  return (
    <div className="rounded-2xl border border-gray-100 bg-white p-6 shadow-sm">
      <div className="flex items-start justify-between gap-3">
        <p className="text-[11px] font-semibold uppercase tracking-widest text-gray-400">
          {label}
        </p>
        {hint ? (
          <button
            type="button"
            title={hint}
            aria-label={hint}
            className="shrink-0 rounded-full p-1 text-gray-400 transition-colors hover:text-gray-600 focus:outline-none focus:ring-2 focus:ring-brand/30"
          >
            <svg width="16" height="16" viewBox="0 0 24 24" fill="none" aria-hidden>
              <circle cx="12" cy="12" r="9" stroke="currentColor" strokeWidth="1.5" />
              <path
                d="M12 11v5M12 8h.01"
                stroke="currentColor"
                strokeWidth="1.5"
                strokeLinecap="round"
              />
            </svg>
          </button>
        ) : null}
      </div>
      {empty ? (
        <div className="mt-2">
          {emptyIcon === "check" ? (
            <div className="flex items-start gap-3">
              <span
                className="mt-0.5 flex h-8 w-8 shrink-0 items-center justify-center rounded-full bg-emerald-50 text-emerald-600"
                aria-hidden
              >
                <svg width="16" height="16" viewBox="0 0 24 24" fill="none">
                  <path
                    d="M12 3l7 3v5c0 5-3.5 8.5-7 10-3.5-1.5-7-5-7-10V6l7-3z"
                    stroke="currentColor"
                    strokeWidth="1.5"
                    strokeLinejoin="round"
                  />
                  <path
                    d="M9.5 12l1.8 1.8L14.8 10"
                    stroke="currentColor"
                    strokeWidth="1.5"
                    strokeLinecap="round"
                    strokeLinejoin="round"
                  />
                </svg>
              </span>
              <div className="min-w-0 pt-0.5">
                <p className="text-sm font-medium text-gray-800">
                  {emptyCaption ?? "All caught up"}
                </p>
              </div>
            </div>
          ) : (
            <>
              <p className="font-mono text-3xl font-semibold text-gray-300">—</p>
              {emptyCaption ? (
                <p className="mt-1.5 text-xs text-gray-400">{emptyCaption}</p>
              ) : null}
            </>
          )}
        </div>
      ) : (
        <p className="mt-2 font-mono text-3xl font-semibold text-gray-900">{value}</p>
      )}
    </div>
  );
}
