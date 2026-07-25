"use client";

type Props = {
  sourceLabel: string;
  values: Record<string, number | undefined>;
  fieldLabels?: Record<string, string>;
  applied: boolean;
  differsFromInput?: boolean;
  busy?: boolean;
  onLoad: () => void;
  onUse: () => void;
  onDismiss: () => void;
  loadLabel?: string;
};

/**
 * Suggestion chrome lives *below* inputs — never auto-fills controlled values.
 * CA must Load, then Use, or Dismiss.
 */
export function DraftSuggestionBanner({
  sourceLabel,
  values,
  fieldLabels,
  applied,
  differsFromInput,
  busy,
  onLoad,
  onUse,
  onDismiss,
  loadLabel = "Load suggestions",
}: Props) {
  const entries = Object.entries(values).filter(
    ([, v]) => v != null && Number.isFinite(v)
  );
  const hasValues = entries.length > 0;

  return (
    <div className="mt-2 rounded-lg border border-dashed border-amber-300/80 bg-amber-50/40 px-3 py-2.5">
      <div className="flex flex-wrap items-start justify-between gap-2">
        <div>
          <p className="text-[11px] font-semibold uppercase tracking-wide text-amber-900/80">
            Unconfirmed suggestion
          </p>
          <p className="mt-0.5 text-[12px] text-amber-950/70">
            Not applied until you click Use — not a pre-filled fact from GSTN.
            An empty result after Load means suggestions are not wired yet, not
            that the amount is confirmed zero.
          </p>
        </div>
        {!hasValues ? (
          <button
            type="button"
            disabled={busy}
            onClick={onLoad}
            className="rounded-full border border-amber-800/20 bg-white px-3 py-1 text-[12px] font-semibold text-amber-950 hover:bg-amber-50 disabled:opacity-40"
          >
            {busy ? "Loading…" : loadLabel}
          </button>
        ) : null}
      </div>

      {hasValues ? (
        <div className="mt-2 space-y-1.5">
          <p className="text-[12px] text-amber-950/80">
            Suggested from {sourceLabel}:
          </p>
          <ul className="font-mono text-[12px] text-amber-950">
            {entries.map(([key, val]) => (
              <li key={key}>
                {(fieldLabels && fieldLabels[key]) || key}:{" "}
                {Number(val).toLocaleString("en-IN")}
              </li>
            ))}
          </ul>
          {differsFromInput ? (
            <p className="text-[11px] font-medium text-amber-900">
              Your entry differs from this suggestion.
            </p>
          ) : null}
          {applied ? (
            <p className="text-[11px] text-amber-900/70">
              Was suggested from {sourceLabel} — you accepted it into the form.
            </p>
          ) : (
            <div className="flex flex-wrap gap-2 pt-1">
              <button
                type="button"
                onClick={onUse}
                className="rounded-full bg-amber-900 px-3 py-1 text-[12px] font-semibold text-white hover:opacity-90"
              >
                Use suggestion
              </button>
              <button
                type="button"
                onClick={onDismiss}
                className="rounded-full px-3 py-1 text-[12px] font-medium text-amber-900/70 hover:bg-amber-100/60"
              >
                Dismiss
              </button>
            </div>
          )}
        </div>
      ) : null}
    </div>
  );
}
