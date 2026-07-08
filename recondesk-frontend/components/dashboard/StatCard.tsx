export function StatCard({
  label,
  value,
  hint,
  empty = false,
  emptyCaption,
}: {
  label: string;
  value: React.ReactNode;
  /** Shown on the info icon tooltip (replaces decorative corner icons). */
  hint?: string;
  empty?: boolean;
  emptyCaption?: string;
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
          <p className="font-mono text-3xl font-semibold text-gray-300">—</p>
          {emptyCaption ? (
            <p className="mt-1.5 text-xs text-gray-400">{emptyCaption}</p>
          ) : null}
        </div>
      ) : (
        <p className="mt-2 font-mono text-3xl font-semibold text-gray-900">{value}</p>
      )}
    </div>
  );
}
