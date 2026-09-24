/**
 * Statutory GST Compliance & Countdown Domain Logic
 * Handles Indian GST statutory filing deadlines, countdown computations,
 * cycle phase tracking, and period compliance evaluation.
 */

export type StatutoryReturnKind = "GSTR-1" | "GSTR-2B" | "GSTR-3B" | "IFF";

export type UrgencyLevel = "critical" | "warning" | "approaching" | "normal";

export interface StatutoryDeadlineItem {
  kind: StatutoryReturnKind;
  title: string;
  statutoryDay: number;
  targetDate: Date;
  targetDateFormatted: string;
  daysRemaining: number;
  hoursRemaining: number;
  totalHours: number;
  isPastDue: boolean;
  urgency: UrgencyLevel;
  urgencyLabel: string;
  description: string;
  statutoryRule: string;
}

export type ComplianceCyclePhase =
  | "OUTWARD_FILING"       // 1st - 11th: Outward supplies window (GSTR-1)
  | "GSTR2B_BUFFER"        // 12th - 13th: GSTN compiles GSTR-2B
  | "RECON_GOLDEN_WINDOW"  // 14th - 20th: Golden window for 2B ↔ PR Recon & Table 4 Lock
  | "POST_FILING_AUDIT";   // 21st - End of Month: Post-filing review & Rule 37 tracking

export interface ComplianceCycleStatus {
  currentISTTimeFormatted: string;
  currentDayOfMonth: number;
  phase: ComplianceCyclePhase;
  phaseTitle: string;
  phaseSubtitle: string;
  recommendedAction: string;
  accentColor: "emerald" | "amber" | "indigo" | "rose";
  deadlines: StatutoryDeadlineItem[];
}

export interface PeriodComplianceStatus {
  period: string;
  statutoryGstr1DateFormatted: string;
  statutoryGstr3bDateFormatted: string;
  isLocked: boolean;
  status: "COMPLIANT_ON_TIME" | "FINALIZED_LATE" | "PENDING_ON_TRACK" | "OVERDUE";
  statusLabel: string;
  statusBadgeCls: string;
  detail: string;
}

export interface NetItcCalculation {
  netClaimablePaise: number;
  netClaimableRupees: number;
  eligibleRupees: number;
  reversedRupees: number;
  reclaimedRupees: number;
  onHoldRupees: number;
  atRiskRupees: number;
  missedRupees: number;
  healthRating: "HEALTHY" | "MODERATE_RISK" | "HIGH_RISK";
  healthLabel: string;
  healthDescription: string;
}

const MONTH_NAMES = [
  "Jan", "Feb", "Mar", "Apr", "May", "Jun",
  "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"
];

const FULL_MONTH_NAMES = [
  "January", "February", "March", "April", "May", "June",
  "July", "August", "September", "October", "November", "December"
];

/**
 * Returns a Date object representing the given timestamp in Indian Standard Time (UTC+05:30).
 */
export function toIST(date: Date = new Date()): Date {
  const utc = date.getTime() + date.getTimezoneOffset() * 60000;
  return new Date(utc + 5.5 * 3600000);
}

function formatDateIST(d: Date): string {
  const day = d.getDate();
  const m = MONTH_NAMES[d.getMonth()];
  const y = d.getFullYear();
  return `${day} ${m} ${y}`;
}

/**
 * Computes the statutory deadlines (GSTR-1 on the 11th, GSTR-2B on the 14th, GSTR-3B on the 20th)
 * relative to the provided reference date.
 */
export function calculateStatutoryDeadlines(refDate: Date = new Date()): ComplianceCycleStatus {
  const ist = toIST(refDate);
  const curYear = ist.getFullYear();
  const curMonth = ist.getMonth();
  const curDay = ist.getDate();
  const nowMs = ist.getTime();

  // Helper to construct a deadline target date in IST
  function getDeadlineTarget(day: number, monthOffset: number = 0): Date {
    const targetMonth = curMonth + monthOffset;
    const d = new Date(curYear, targetMonth, day, 23, 59, 59, 999);
    return d;
  }

  // Determine current cycle phase
  let phase: ComplianceCyclePhase;
  let phaseTitle: string;
  let phaseSubtitle: string;
  let recommendedAction: string;
  let accentColor: "emerald" | "amber" | "indigo" | "rose";

  if (curDay <= 11) {
    phase = "OUTWARD_FILING";
    phaseTitle = "Outward Filing Window (GSTR-1)";
    phaseSubtitle = "Suppliers are uploading outward invoices before the 11th midnight cutoff.";
    recommendedAction = "Verify critical vendor submission status and send follow-ups to habitual late filers.";
    accentColor = "amber";
  } else if (curDay <= 13) {
    phase = "GSTR2B_BUFFER";
    phaseTitle = "GSTN GSTR-2B Compilation Window";
    phaseSubtitle = "GST Portal is processing GSTR-1 filings and compiling static GSTR-2B statements.";
    recommendedAction = "Ensure all internal purchase register entries are finalized in Tally/ERP before 2B release.";
    accentColor = "indigo";
  } else if (curDay <= 20) {
    phase = "RECON_GOLDEN_WINDOW";
    phaseTitle = "Reconciliation & Claim Golden Window";
    phaseSubtitle = "GSTR-2B is live! This is the critical window to match records and lock GSTR-3B Table 4.";
    recommendedAction = "Run 2B ↔ PR reconciliation, address Section 17(5) and Rule 37 reversals, and finalize Table 4.";
    accentColor = "emerald";
  } else {
    phase = "POST_FILING_AUDIT";
    phaseTitle = "Post-Filing Audit & Prior Period Review";
    phaseSubtitle = "Monthly filing cutoff passed. Review unrecovered ITC and prepare for upcoming cycle.";
    recommendedAction = "Audit pending vendor disputes, track 180-day Rule 37 aging, and download fresh GSTN ledgers.";
    accentColor = "emerald";
  }

  // 1. GSTR-1 Deadline (11th)
  // If curDay > 11, the next GSTR-1 deadline is the 11th of next month
  const gstr1Target = curDay <= 11 ? getDeadlineTarget(11, 0) : getDeadlineTarget(11, 1);
  const gstr1Ms = gstr1Target.getTime() - nowMs;
  const gstr1Hours = Math.max(0, Math.floor(gstr1Ms / 3600000));
  const gstr1Days = Math.floor(gstr1Hours / 24);

  // 2. GSTR-2B Release (14th)
  // If curDay > 14, next release is 14th of next month
  const gstr2bTarget = curDay <= 14 ? getDeadlineTarget(14, 0) : getDeadlineTarget(14, 1);
  const gstr2bMs = gstr2bTarget.getTime() - nowMs;
  const gstr2bHours = Math.max(0, Math.floor(gstr2bMs / 3600000));
  const gstr2bDays = Math.floor(gstr2bHours / 24);

  // 3. GSTR-3B Deadline (20th)
  // If curDay > 20, next deadline is 20th of next month
  const gstr3bTarget = curDay <= 20 ? getDeadlineTarget(20, 0) : getDeadlineTarget(20, 1);
  const gstr3bMs = gstr3bTarget.getTime() - nowMs;
  const gstr3bHours = Math.max(0, Math.floor(gstr3bMs / 3600000));
  const gstr3bDays = Math.floor(gstr3bHours / 24);

  function getUrgency(days: number): { urgency: UrgencyLevel; label: string } {
    if (days <= 2) return { urgency: "critical", label: `${days}d left — Critical` };
    if (days <= 5) return { urgency: "warning", label: `${days}d left — Urgent` };
    if (days <= 10) return { urgency: "approaching", label: `${days}d left — Approaching` };
    return { urgency: "normal", label: `${days}d left — On Track` };
  }

  const g1U = getUrgency(gstr1Days);
  const g2U = curDay >= 14 && curDay <= 20
    ? { urgency: "normal" as const, label: "Live & Available" }
    : getUrgency(gstr2bDays);
  const g3U = getUrgency(gstr3bDays);

  const deadlines: StatutoryDeadlineItem[] = [
    {
      kind: "GSTR-1",
      title: "GSTR-1 (Outward Supplies)",
      statutoryDay: 11,
      targetDate: gstr1Target,
      targetDateFormatted: formatDateIST(gstr1Target),
      daysRemaining: gstr1Days,
      hoursRemaining: gstr1Hours % 24,
      totalHours: gstr1Hours,
      isPastDue: false,
      urgency: g1U.urgency,
      urgencyLabel: g1U.label,
      description: "Monthly return of outward supplies & debit/credit notes",
      statutoryRule: "Section 37(1) · Due 11th of succeeding month",
    },
    {
      kind: "GSTR-2B",
      title: "GSTR-2B (Static Statement)",
      statutoryDay: 14,
      targetDate: gstr2bTarget,
      targetDateFormatted: formatDateIST(gstr2bTarget),
      daysRemaining: gstr2bDays,
      hoursRemaining: gstr2bHours % 24,
      totalHours: gstr2bHours,
      isPastDue: false,
      urgency: g2U.urgency,
      urgencyLabel: g2U.label,
      description: "Static auto-drafted ITC statement generated by GSTN",
      statutoryRule: "Rule 60(7) · Auto-generated on 14th following GSTR-1 cutoff",
    },
    {
      kind: "GSTR-3B",
      title: "GSTR-3B (Summary Return)",
      statutoryDay: 20,
      targetDate: gstr3bTarget,
      targetDateFormatted: formatDateIST(gstr3bTarget),
      daysRemaining: gstr3bDays,
      hoursRemaining: gstr3bHours % 24,
      totalHours: gstr3bHours,
      isPastDue: false,
      urgency: g3U.urgency,
      urgencyLabel: g3U.label,
      description: "Summary tax payment & Table 4 ITC claim return",
      statutoryRule: "Section 39(1) · Due 20th of succeeding month",
    },
  ];

  return {
    currentISTTimeFormatted: `${curDay} ${FULL_MONTH_NAMES[curMonth]} ${curYear}`,
    currentDayOfMonth: curDay,
    phase,
    phaseTitle,
    phaseSubtitle,
    recommendedAction,
    accentColor,
    deadlines,
  };
}

/**
 * Evaluates the statutory compliance status of a specific tax period (e.g. "2026-08").
 */
export function evaluatePeriodCompliance(
  periodStr: string,
  isLocked: boolean,
  finalizedAt?: string | null,
  refDate: Date = new Date()
): PeriodComplianceStatus {
  const parts = periodStr.split("-");
  const year = parseInt(parts[0], 10);
  const month = parseInt(parts[1], 10); // 1-12

  if (isNaN(year) || isNaN(month) || month < 1 || month > 12) {
    return {
      period: periodStr,
      statutoryGstr1DateFormatted: "—",
      statutoryGstr3bDateFormatted: "—",
      isLocked,
      status: "PENDING_ON_TRACK",
      statusLabel: "Period Active",
      statusBadgeCls: "bg-gray-100 text-gray-700 border-gray-200",
      detail: `Tax period ${periodStr}`,
    };
  }

  // The filing month is month + 1
  let filingYear = year;
  let filingMonth = month; // in 0-indexed JS: month (e.g. Aug is 8, filing month Sep is index 8)
  if (filingMonth > 11) {
    filingMonth = 0;
    filingYear += 1;
  }

  const statutoryGstr1Date = new Date(filingYear, filingMonth, 11, 23, 59, 59, 999);
  const statutoryGstr3bDate = new Date(filingYear, filingMonth, 20, 23, 59, 59, 999);

  const istNow = toIST(refDate);
  const isPast3bDeadline = istNow.getTime() > statutoryGstr3bDate.getTime();

  const g1Formatted = formatDateIST(statutoryGstr1Date);
  const g3bFormatted = formatDateIST(statutoryGstr3bDate);

  if (isLocked) {
    const finTime = finalizedAt ? new Date(finalizedAt).getTime() : 0;
    const onTime = finTime > 0 && finTime <= statutoryGstr3bDate.getTime();
    if (onTime) {
      return {
        period: periodStr,
        statutoryGstr1DateFormatted: g1Formatted,
        statutoryGstr3bDateFormatted: g3bFormatted,
        isLocked: true,
        status: "COMPLIANT_ON_TIME",
        statusLabel: "Compliant & Finalized On-Time",
        statusBadgeCls: "bg-emerald-100 text-emerald-800 border-emerald-300",
        detail: `Locked before statutory cutoff (${g3bFormatted}). Certified for Table 4 filing.`,
      };
    }
    return {
      period: periodStr,
      statutoryGstr1DateFormatted: g1Formatted,
      statutoryGstr3bDateFormatted: g3bFormatted,
      isLocked: true,
      status: "FINALIZED_LATE",
      statusLabel: "Finalized & Locked",
      statusBadgeCls: "bg-blue-100 text-blue-800 border-blue-300",
      detail: `Finalized and locked. Retains certified audit trail for statutory audit.`,
    };
  }

  if (isPast3bDeadline) {
    return {
      period: periodStr,
      statutoryGstr1DateFormatted: g1Formatted,
      statutoryGstr3bDateFormatted: g3bFormatted,
      isLocked: false,
      status: "OVERDUE",
      statusLabel: "Filing Deadline Elapsed",
      statusBadgeCls: "bg-rose-100 text-rose-800 border-rose-300",
      detail: `Statutory cutoff was ${g3bFormatted}. Finalize run to avoid DRC-01C notices & interest.`,
    };
  }

  return {
    period: periodStr,
    statutoryGstr1DateFormatted: g1Formatted,
    statutoryGstr3bDateFormatted: g3bFormatted,
    isLocked: false,
    status: "PENDING_ON_TRACK",
    statusLabel: "Open Provisional Draft",
    statusBadgeCls: "bg-amber-100 text-amber-900 border-amber-300",
    detail: `Due on ${g3bFormatted}. Resolve blocking exceptions before final lock.`,
  };
}

/**
 * Computes net claimable ITC and overall reconciliation portfolio health.
 */
export function calculateNetClaimableItc(kpis: {
  eligible_itc: number;
  reversed_itc: number;
  reclaimed_itc: number;
  on_hold_itc?: number;
  at_risk_itc?: number;
  missed_itc?: number;
}): NetItcCalculation {
  const eligible = Number(kpis.eligible_itc || 0);
  const reversed = Number(kpis.reversed_itc || 0);
  const reclaimed = Number(kpis.reclaimed_itc || 0);
  const onHold = Number(kpis.on_hold_itc || 0);
  const atRisk = Number(kpis.at_risk_itc || 0);
  const missed = Number(kpis.missed_itc || 0);

  const netClaimable = Math.max(0, eligible - reversed + reclaimed);
  const netPaise = Math.round(netClaimable * 100);

  let healthRating: "HEALTHY" | "MODERATE_RISK" | "HIGH_RISK";
  let healthLabel: string;
  let healthDescription: string;

  if (atRisk > 0 && atRisk > eligible * 0.2) {
    healthRating = "HIGH_RISK";
    healthLabel = "High Audit Risk";
    healthDescription = "At-risk wrongful ITC exceeds 20% of eligible claim — severe DRC-01C exposure under Rule 88D.";
  } else if (atRisk > 0 || missed > eligible * 0.15) {
    healthRating = "MODERATE_RISK";
    healthLabel = "Attention Required";
    healthDescription = "Unclaimed missed ITC or active supplier discrepancies require CA review.";
  } else {
    healthRating = "HEALTHY";
    healthLabel = "Statutory Clean";
    healthDescription = "ITC matches 2B baseline within statutory tolerances. Low audit exposure.";
  }

  return {
    netClaimablePaise: netPaise,
    netClaimableRupees: netClaimable,
    eligibleRupees: eligible,
    reversedRupees: reversed,
    reclaimedRupees: reclaimed,
    onHoldRupees: onHold,
    atRiskRupees: atRisk,
    missedRupees: missed,
    healthRating,
    healthLabel,
    healthDescription,
  };
}
