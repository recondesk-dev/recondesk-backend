import type { ReconciliationStatus } from "@/lib/types";

const STYLES: Record<
  ReconciliationStatus,
  { wrap: string; dot: string; dotAnim?: string }
> = {
  PENDING: {
    wrap: "bg-[#F3F4F6] text-[#6B7280]",
    dot: "bg-[#9CA3AF]",
  },
  IMPORTING: {
    wrap: "bg-[#EFF6FF] text-[#3B82F6]",
    dot: "bg-[#3B82F6]",
  },
  MATCHING: {
    wrap: "bg-[#EFF6FF] text-[#3B82F6]",
    dot: "bg-[#3B82F6] relative",
    dotAnim: "animate-ping absolute inline-flex h-full w-full rounded-full bg-[#3B82F6] opacity-75",
  },
  COMPLETE: {
    wrap: "bg-[#ECFDF5] text-[#10B981]",
    dot: "bg-[#10B981]",
  },
  FINALIZED: {
    wrap: "bg-brand-dim text-brand",
    dot: "bg-brand",
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
  COMPLETE: "Complete",
  FINALIZED: "Finalized",
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
      className={`inline-flex items-center gap-1.5 rounded-full px-2.5 py-0.5 text-xs font-medium ${s.wrap}`}
    >
      <span className="relative flex h-1 w-1 shrink-0 items-center justify-center">
        {status === "MATCHING" && (
          <span className={`h-1 w-1 rounded-full ${s.dotAnim ?? ""}`} aria-hidden />
        )}
        <span className={`h-1 w-1 rounded-full ${s.dot}`} />
      </span>
      {LABELS[status]}
      {finalizedLock && (
        <svg className="h-3 w-3 shrink-0" viewBox="0 0 24 24" fill="currentColor" aria-hidden>
          <path d="M12 1a5 5 0 00-5 5v3H6a2 2 0 00-2 2v10a2 2 0 002 2h12a2 2 0 002-2V11a2 2 0 00-2-2h-1V6a5 5 0 00-5-5zm-3 8V6a3 3 0 116 0v3H9z" />
        </svg>
      )}
    </span>
  );
}
