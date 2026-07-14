import type { ReconciliationStatus } from "@/lib/types";

/**
 * Display mapping only — do not rename ReconciliationStatus enum values.
 * COMPLETE = engine finished matching (not user sign-off). FINALIZED = Finalize clicked.
 */
const STYLES: Record<
  ReconciliationStatus,
  { wrap: string; dot: string; dotAnim?: string }
> = {
  PENDING: {
    wrap: "bg-[#F0F0F0] text-[#6B7280]",
    dot: "bg-[#9CA3AF]",
  },
  IMPORTING: {
    wrap: "bg-[#F0F0F0] text-[#4B5563]",
    dot: "bg-[#6B7280]",
  },
  MATCHING: {
    wrap: "bg-[#F0F0F0] text-[#4B5563]",
    dot: "bg-[#111111] relative",
    dotAnim: "animate-ping absolute inline-flex h-full w-full rounded-full bg-[#111111] opacity-40",
  },
  COMPLETE: {
    wrap: "bg-[#111111] text-white",
    dot: "bg-white",
  },
  FINALIZED: {
    wrap: "bg-[#F0F0F0] text-[#374151]",
    dot: "bg-[#111111]",
  },
  FAILED: {
    wrap: "bg-[#FEF2F2] text-[#EF4444]",
    dot: "bg-[#EF4444]",
  },
};

const LABELS: Record<ReconciliationStatus, string> = {
  PENDING: "Pending",
  IMPORTING: "Importing",
  MATCHING: "Matching",
  COMPLETE: "Ready for Review",
  FINALIZED: "Complete",
  FAILED: "Failed",
};

export function StatusBadge({
  status,
  finalizedLock,
}: {
  status: ReconciliationStatus;
  finalizedLock?: boolean;
}) {
  const s = STYLES[status];
  return (
    <span
      className={`inline-flex items-center gap-1.5 rounded-full px-3 py-1 text-xs font-medium ${s.wrap}`}
    >
      <span className="relative flex h-1.5 w-1.5 shrink-0 items-center justify-center">
        {status === "MATCHING" && (
          <span className={`h-1.5 w-1.5 rounded-full ${s.dotAnim ?? ""}`} aria-hidden />
        )}
        <span className={`h-1.5 w-1.5 rounded-full ${s.dot}`} />
      </span>
      {LABELS[status]}
      {status === "FINALIZED" ? (
        <svg className="h-3 w-3 shrink-0" viewBox="0 0 24 24" fill="none" aria-hidden>
          <path
            d="M5 12.5l4.5 4.5L19 7.5"
            stroke="currentColor"
            strokeWidth="2.25"
            strokeLinecap="round"
            strokeLinejoin="round"
          />
        </svg>
      ) : finalizedLock ? (
        <svg className="h-3 w-3 shrink-0" viewBox="0 0 24 24" fill="currentColor" aria-hidden>
          <path d="M12 1a5 5 0 00-5 5v3H6a2 2 0 00-2 2v10a2 2 0 002 2h12a2 2 0 002-2V11a2 2 0 00-2-2h-1V6a5 5 0 00-5-5zm-3 8V6a3 3 0 116 0v3H9z" />
        </svg>
      ) : null}
    </span>
  );
}
