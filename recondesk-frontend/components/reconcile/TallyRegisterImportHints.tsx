"use client";

import Link from "next/link";

import type { RegisterTypeDetection, RegisterValidationIssue } from "@/lib/api";

const TYPE_LABEL: Record<"purchase" | "sales" | "ambiguous", string> = {
  purchase: "Purchase Register",
  sales: "Sales Register",
  ambiguous: "Unknown register type",
};

function IssueList({ issues }: { issues: RegisterValidationIssue[] }) {
  if (!issues.length) return null;
  return (
    <ul className="mt-2 space-y-1.5">
      {issues.map((issue) => {
        const tone =
          issue.severity === "error"
            ? "text-red-800"
            : issue.severity === "warning"
              ? "text-amber-900"
              : "text-gray-600";
        return (
          <li key={issue.code} className={`text-[12px] leading-relaxed ${tone}`}>
            {issue.severity === "error"
              ? "✕ "
              : issue.severity === "warning"
                ? "⚠ "
                : "• "}
            {issue.message}
          </li>
        );
      })}
    </ul>
  );
}

/** Short how-to for exporting Purchase / Sales registers from Tally. */
export function TallyExportHelp({
  registerType,
  helpCopy,
}: {
  registerType: "purchase" | "sales";
  helpCopy?: string | null;
}) {
  const fallback =
    registerType === "purchase"
      ? "In TallyPrime: Gateway of Tally → Display More Reports → Statutory Reports → GST → GSTR-2 / Purchase Register → Alt+E → Excel or CSV. In ERP 9: Display → Statutory Reports → GST → GSTR-2 → Export."
      : "In TallyPrime: Gateway of Tally → Display More Reports → Statutory Reports → GST → GSTR-1 / Sales Register → Alt+E → Excel or CSV. In ERP 9: Display → Statutory Reports → GST → GSTR-1 → Export. Include Invoice Type (B2B/B2C) when available.";

  return (
    <details className="rounded-lg border border-[var(--border)] bg-[#FAFAFA] px-3 py-2 text-[12px] text-gray-600">
      <summary className="cursor-pointer font-medium text-[var(--ink)]">
        How to export from Tally ({registerType === "purchase" ? "Purchase" : "Sales"}{" "}
        Register)
      </summary>
      <p className="mt-2 leading-relaxed">{helpCopy?.trim() || fallback}</p>
    </details>
  );
}

type Props = {
  detection: RegisterTypeDetection | null;
  /** Pipeline this page belongs to */
  expectedType: "purchase" | "sales";
  clientId?: string | null;
  overridden: boolean;
  onOverride: (type: "purchase" | "sales") => void;
  onClearOverride?: () => void;
  busy?: boolean;
};

/**
 * Shows detected register type (Purchase vs Sales), Tally Export profile,
 * pipeline mismatch redirect, and manual override when ambiguous.
 */
export function RegisterTypeDetectionBanner({
  detection,
  expectedType,
  clientId,
  overridden,
  onOverride,
  onClearOverride,
  busy,
}: Props) {
  if (!detection) return null;

  const detected = detection.register_type;
  const mismatch =
    !overridden &&
    !!detection.pipeline_mismatch &&
    detected !== "ambiguous" &&
    detected !== expectedType;

  const needsChoice =
    !overridden &&
    (detection.requires_manual_choice || detected === "ambiguous");

  const otherHref =
    detected === "sales"
      ? clientId
        ? `/reconcile/gstr1/new?client_gstin_id=${encodeURIComponent(clientId)}`
        : "/reconcile/gstr1/new"
      : clientId
        ? `/reconcile/${clientId}/new`
        : "/clients";

  const effectiveLabel = overridden
    ? TYPE_LABEL[expectedType]
    : TYPE_LABEL[detected];

  return (
    <div className="space-y-3">
      <div
        className={
          mismatch
            ? "rounded-lg border border-amber-300 bg-amber-50 p-3 text-sm text-amber-950"
            : needsChoice
              ? "rounded-lg border border-amber-300 bg-amber-50 p-3 text-sm text-amber-950"
              : "rounded-lg border border-emerald-200 bg-emerald-50/80 p-3 text-sm text-emerald-950"
        }
      >
        <div className="font-medium">
          {detection.is_tally_export ? "Tally Export detected · " : ""}
          {overridden
            ? `Using ${TYPE_LABEL[expectedType]} (manual override)`
            : needsChoice
              ? "Could not tell Purchase from Sales — choose a type to continue"
              : `Detected: ${effectiveLabel}`}
          {!needsChoice && !overridden && detection.confidence !== "high" ? (
            <span className="ml-1 font-normal text-[12px] opacity-80">
              ({detection.confidence} confidence)
            </span>
          ) : null}
        </div>

        {mismatch ? (
          <p className="mt-1 text-[12px] leading-relaxed">
            This file looks like a {TYPE_LABEL[detected as "purchase" | "sales"]}, but
            you are on the{" "}
            {expectedType === "purchase" ? "GSTR-2B (Purchase)" : "GSTR-1 (Sales)"}{" "}
            import.{" "}
            <Link href={otherHref} className="font-semibold underline">
              Open the matching pipeline
            </Link>{" "}
            or override below to continue here.
          </p>
        ) : null}

        {detection.reasons?.length && (needsChoice || mismatch) ? (
          <ul className="mt-2 list-inside list-disc text-[11px] text-amber-900/80">
            {detection.reasons.slice(0, 4).map((r) => (
              <li key={r}>{r}</li>
            ))}
          </ul>
        ) : null}

        {(needsChoice || mismatch || overridden) && (
          <div className="mt-3 flex flex-wrap items-center gap-2">
            <span className="text-[11px] font-medium uppercase tracking-wide text-gray-500">
              Treat as:
            </span>
            <button
              type="button"
              disabled={busy}
              onClick={() => onOverride("purchase")}
              className={
                (overridden ? expectedType : detected) === "purchase" &&
                (overridden || !needsChoice)
                  ? "rounded-full bg-[var(--ink)] px-3 py-1 text-[12px] font-semibold text-white"
                  : "rounded-full bg-white px-3 py-1 text-[12px] font-semibold text-gray-700 ring-1 ring-gray-200 hover:bg-gray-50"
              }
            >
              Purchase Register
            </button>
            <button
              type="button"
              disabled={busy}
              onClick={() => onOverride("sales")}
              className={
                (overridden ? expectedType : detected) === "sales" &&
                (overridden || !needsChoice)
                  ? "rounded-full bg-[var(--ink)] px-3 py-1 text-[12px] font-semibold text-white"
                  : "rounded-full bg-white px-3 py-1 text-[12px] font-semibold text-gray-700 ring-1 ring-gray-200 hover:bg-gray-50"
              }
            >
              Sales Register
            </button>
            {overridden && onClearOverride ? (
              <button
                type="button"
                onClick={onClearOverride}
                className="text-[12px] text-[var(--ink)] underline"
              >
                Clear override
              </button>
            ) : null}
          </div>
        )}

        <IssueList issues={detection.validation_issues ?? []} />
      </div>

      <TallyExportHelp
        registerType={expectedType}
        helpCopy={detection.context_help_copy || detection.help_copy}
      />
    </div>
  );
}
