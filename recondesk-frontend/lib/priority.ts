import type { ComplianceRisk, ReconciliationRun, ReconciliationStatus } from "./types";

export function computePriorityScore(run: ReconciliationRun | null): number {
  if (!run) return 10;
  if (run.status === "FAILED") return 95;
  if (run.status === "FINALIZED") return 0;

  let score = 0;

  const itcScore = Math.min(((run.missedItc ?? 0) / 100000) * 50, 50);
  score += itcScore;

  const riskMap: Record<ComplianceRisk, number> = {
    LOW: 0,
    MEDIUM: 10,
    HIGH: 20,
    CRITICAL: 30,
  };
  score += riskMap[run.complianceRisk ?? "LOW"];

  const statusMap: Partial<Record<ReconciliationStatus, number>> = {
    COMPLETE: 20,
    PENDING: 10,
    IMPORTING: 5,
    MATCHING: 5,
  };
  score += statusMap[run.status] ?? 0;

  return Math.round(score);
}
