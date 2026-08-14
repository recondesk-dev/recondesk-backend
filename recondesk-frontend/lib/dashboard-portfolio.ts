import type {
  AuthMeProfile,
  ClientGstin,
  ReconcileRunListRow,
  TeamMemberListItem,
} from "@/lib/api";
import { computePriorityScore } from "@/lib/priority";
import type {
  Client,
  ClientPortfolioRow,
  ComplianceRisk,
  DashboardStats,
  PaginatedPortfolioResponse,
  PortfolioFilters,
  PortfolioSortKey,
  PortfolioStatusFilter,
  ReconciliationRun,
  ReconciliationStatus,
  SortDirection,
  Staff,
} from "@/lib/types";

export const DW = "dw" as const;

const MONTHS = [
  "Jan",
  "Feb",
  "Mar",
  "Apr",
  "May",
  "Jun",
  "Jul",
  "Aug",
  "Sep",
  "Oct",
  "Nov",
  "Dec",
] as const;

export function formatPeriodLabel(period: string): string {
  const p = (period || "").trim();
  const m = /^(\d{4})-(\d{2})$/.exec(p);
  if (!m) return p;
  const y = m[1];
  const mo = Math.max(1, Math.min(12, parseInt(m[2], 10))) - 1;
  return `${MONTHS[mo] ?? m[2]} ${y}`;
}

export function mapBackendRunStatus(raw: string): ReconciliationStatus {
  const u = (raw || "").trim().toUpperCase();
  // COMPLETED/COMPLETE = processing finished (display as "Ready for Review").
  // FINAL = user finalized (display as green "Complete"). Enum names are ambiguous; do not rename here.
  if (u === "COMPLETED") return "COMPLETE";
  if (u === "FINAL") return "FINALIZED";
  if (u === "FAILED") return "FAILED";
  if (u === "MATCHING" || u === "PROCESSING" || u === "READY") return "MATCHING";
  if (u === "PENDING") return "PENDING";
  if (
    [
      "UPLOADING",
      "QUEUED",
      "GSTR_IMPORT_COMPLETE",
      "PURCHASE_IMPORT_COMPLETE",
      "DRAFT",
      "GSTR_UPLOADED",
      "PR_UPLOADED",
    ].includes(u)
  ) {
    return "IMPORTING";
  }
  return "PENDING";
}

export function paiseToRupee(paise: number | null | undefined): number | null {
  if (paise == null || Number.isNaN(Number(paise))) return null;
  return Math.round(Number(paise)) / 100;
}

function inferComplianceRisk(
  missedRupee: number | null,
  wrongfulRupee: number | null,
  uiStatus: ReconciliationStatus
): ComplianceRisk | null {
  if (uiStatus !== "COMPLETE" && uiStatus !== "FINALIZED") return null;
  const wr = wrongfulRupee ?? 0;
  const mi = missedRupee ?? 0;
  if (wr >= 500_000) return "CRITICAL";
  if (wr >= 100_000 || mi >= 2_000_000) return "HIGH";
  if (mi >= 400_000) return "MEDIUM";
  return "LOW";
}

function matchRateFromRow(row: ReconcileRunListRow): number | null {
  const rs = row.run_summary;
  if (rs && typeof rs === "object") {
    const m = rs as Record<string, unknown>;
    const v = m.match_rate_percent;
    if (typeof v === "number" && !Number.isNaN(v)) return Math.round(v * 100) / 100;
    const mc = row.matched_count ?? m.matched_count;
    const gstr = m.gstr_in_scope;
    if (
      typeof mc === "number" &&
      typeof gstr === "number" &&
      gstr > 0 &&
      !Number.isNaN(mc)
    ) {
      return Math.round((mc / gstr) * 10000) / 100;
    }
  }
  return null;
}

/** Prefer explicit summary keys; list rows omit matched ITC paise columns. */
function matchedItcPaiseFromSummary(rs: unknown): number | null {
  if (!rs || typeof rs !== "object") return null;
  const m = rs as Record<string, unknown>;
  for (const k of ["matched_itc_paise", "net_claimable_itc_paise", "total_gstr_itc_paise"] as const) {
    const v = m[k];
    if (typeof v === "number" && !Number.isNaN(v)) return v;
  }
  return null;
}

/**
 * List rows often leave top-level itc_at_risk/wrongful_itc at 0 while the
 * amounts live in run_summary (worker historically only wrote run_summary).
 */
function moneyPaiseFromRow(
  row: ReconcileRunListRow,
  top: number | null | undefined,
  summaryKeys: readonly string[]
): number | null {
  if (typeof top === "number" && !Number.isNaN(top) && top !== 0) return top;
  const rs = row.run_summary;
  if (rs && typeof rs === "object") {
    const m = rs as Record<string, unknown>;
    for (const k of summaryKeys) {
      const v = m[k];
      if (typeof v === "number" && !Number.isNaN(v)) return v;
    }
  }
  if (typeof top === "number" && !Number.isNaN(top)) return top;
  return null;
}

export function initialsFromDisplayName(name: string): string {
  const t = name.trim();
  if (!t) return "?";
  const parts = t.split(/\s+/).filter(Boolean);
  if (parts.length >= 2) {
    const a = parts[0][0];
    const b = parts[parts.length - 1][0];
    return `${a}${b}`.toUpperCase();
  }
  if (parts[0].length >= 2) return parts[0].slice(0, 2).toUpperCase();
  return parts[0][0]?.toUpperCase() ?? "?";
}

export function clientGstinToClient(row: ClientGstin): Client {
  const st = (row.scheme_type || "regular").toLowerCase();
  const rt = (row.registration_type || "").toUpperCase();
  let registrationType: Client["registrationType"] = "Regular";
  if (st === "composition" || rt.includes("COMPOSITION")) registrationType = "Composition";
  else if (rt.includes("SEZ")) registrationType = "SEZ";

  return {
    id: row.id,
    tradeName: (row.trade_name || row.legal_name || row.gstin || "Client").trim(),
    gstin: row.gstin,
    registrationType,
    schemeType: (row.scheme_type || "regular") as Client["schemeType"],
    filingFrequency: (row.filing_frequency || "monthly") as Client["filingFrequency"],
    assignedStaffId: row.assigned_to ?? "",
    createdAt: row.added_at,
    isDemo: Boolean((row as any).is_demo),
  };
}

export function teamMemberToStaff(m: TeamMemberListItem): Staff | null {
  if (m.status !== "active" || !m.member_user_id) return null;
  const roleUpper = (m.role || "").toUpperCase();
  const role: Staff["role"] = roleUpper.includes("ADMIN") ? "ADMIN" : "STAFF";
  const name = m.full_name?.trim() || m.email || "Member";
  return {
    id: m.member_user_id,
    name,
    email: m.email || "",
    role,
    avatarInitials: initialsFromDisplayName(name),
  };
}

export function ownerStaffFromMe(me: AuthMeProfile): Staff {
  const name = me.full_name?.trim() || me.email || "Owner";
  return {
    id: me.id,
    name,
    email: me.email || "",
    role: "ADMIN",
    avatarInitials: initialsFromDisplayName(name),
  };
}

export function buildStaffRoster(
  team: TeamMemberListItem[],
  me: AuthMeProfile | null
): Staff[] {
  const fromTeam = team
    .map((m) => teamMemberToStaff(m))
    .filter((x): x is Staff => x != null);
  const byId = new Map(fromTeam.map((s) => [s.id, s]));
  if (me?.id && !byId.has(me.id)) {
    const o = ownerStaffFromMe(me);
    byId.set(o.id, o);
  }
  return Array.from(byId.values());
}

export function staffForAssignee(staffList: Staff[], assignedUserId: string): Staff {
  const found = staffList.find((s) => s.id === assignedUserId);
  if (found) return found;
  return {
    id: assignedUserId || "unknown",
    name: assignedUserId ? "Team member" : "Unassigned",
    email: "",
    role: "STAFF",
    avatarInitials: "?",
  };
}

/** Run numbers within each period (oldest → newest), matching backend history semantics. */
export function runNumbersForClientRuns(
  runsOldestFirst: ReconcileRunListRow[]
): Map<string, number> {
  const byPeriod: Record<string, number> = {};
  const out = new Map<string, number>();
  for (const r of runsOldestFirst) {
    const p = r.period || "";
    const next = (byPeriod[p] ?? 0) + 1;
    byPeriod[p] = next;
    out.set(r.id, next);
  }
  return out;
}

export function reconcileListRowToUiRun(
  row: ReconcileRunListRow,
  clientUuid: string,
  runNumber: number
): ReconciliationRun {
  const uiStatus = mapBackendRunStatus(row.status);
  const missedRupee = paiseToRupee(
    moneyPaiseFromRow(row, row.itc_at_risk, ["itc_at_risk", "missed_itc_paise"]) ??
      undefined
  );
  const wrongfulRupee = paiseToRupee(
    moneyPaiseFromRow(row, row.wrongful_itc, ["wrongful_itc"]) ?? undefined
  );
  const complianceRisk = inferComplianceRisk(missedRupee, wrongfulRupee, uiStatus);
  const ts =
    row.updated_at || row.completed_at || row.created_at;

  const matchedPaise = matchedItcPaiseFromSummary(row.run_summary);

  return {
    id: row.id,
    clientId: clientUuid,
    period: formatPeriodLabel(row.period),
    runNumber,
    status: uiStatus,
    matchRate: matchRateFromRow(row),
    itcClaimed: paiseToRupee(matchedPaise ?? undefined),
    missedItc: missedRupee,
    complianceRisk,
    errorMessage:
      uiStatus === "FAILED"
        ? (row.status_message || "Reconciliation failed.").slice(0, 2000)
        : null,
    finalizedBy: row.finalized_by_name ?? null,
    finalizedAt: row.finalized_at ?? null,
    createdAt: row.created_at,
    updatedAt: ts,
  };
}

export function buildRunRowsForClient(
  allRuns: ReconcileRunListRow[],
  clientId: string
): ReconciliationRun[] {
  const mine = allRuns.filter((r) => r.client_gstin_id === clientId);
  const oldestFirst = [...mine].sort(
    (a, b) => new Date(a.created_at).getTime() - new Date(b.created_at).getTime()
  );
  const nums = runNumbersForClientRuns(oldestFirst);
  return [...mine]
    .sort(
      (a, b) => new Date(b.created_at).getTime() - new Date(a.created_at).getTime()
    )
    .map((r) =>
      reconcileListRowToUiRun(r, clientId, nums.get(r.id) ?? 1)
    );
}

export function latestRunByClientId(
  runs: ReconcileRunListRow[]
): Map<string, ReconcileRunListRow> {
  const m = new Map<string, ReconcileRunListRow>();
  for (const r of runs) {
    const cid = r.client_gstin_id;
    const prev = m.get(cid);
    if (!prev || new Date(r.created_at) > new Date(prev.created_at)) {
      m.set(cid, r);
    }
  }
  return m;
}

export function buildPortfolioRows(
  clients: ClientGstin[],
  runs: ReconcileRunListRow[],
  staffList: Staff[]
): ClientPortfolioRow[] {
  const latest = latestRunByClientId(runs);
  const numsGlobal = new Map<string, Map<string, number>>();
  for (const c of clients) {
    const mine = runs.filter((r) => r.client_gstin_id === c.id);
    const oldestFirst = [...mine].sort(
      (a, b) =>
        new Date(a.created_at).getTime() - new Date(b.created_at).getTime()
    );
    numsGlobal.set(c.id, runNumbersForClientRuns(oldestFirst));
  }

  return clients.map((cg) => {
    const client = clientGstinToClient(cg);
    const lr = latest.get(cg.id);
    let latestUi: ReconciliationRun | null = null;
    if (lr) {
      const rn = numsGlobal.get(cg.id)?.get(lr.id) ?? 1;
      latestUi = reconcileListRowToUiRun(lr, cg.id, rn);
    }
    return {
      client,
      latestRun: latestUi,
      priorityScore: computePriorityScore(latestUi),
      assignedStaff: staffForAssignee(staffList, client.assignedStaffId),
    };
  });
}

function statusMatchesFilter(
  filterStatus: PortfolioStatusFilter,
  run: ReconciliationRun | null
): boolean {
  if (filterStatus === "ALL") return true;
  if (!run) return filterStatus === "PENDING";
  const s = run.status;
  switch (filterStatus) {
    case "PENDING":
      return s === "PENDING";
    case "IN_PROGRESS":
      return s === "IMPORTING" || s === "MATCHING";
    case "COMPLETE":
      return s === "COMPLETE";
    case "FINALIZED":
      return s === "FINALIZED";
    case "FAILED":
      return s === "FAILED";
    default:
      return true;
  }
}

function missedVal(r: ClientPortfolioRow): number {
  const v = r.latestRun?.missedItc;
  if (v == null) return Number.NEGATIVE_INFINITY;
  return v;
}

function matchVal(r: ClientPortfolioRow): number {
  const v = r.latestRun?.matchRate;
  if (v == null) return Number.NEGATIVE_INFINITY;
  return v;
}

function comparePortfolioRows(
  a: ClientPortfolioRow,
  b: ClientPortfolioRow,
  sortKey: PortfolioSortKey,
  dir: SortDirection
): number {
  const desc = dir === "desc";
  const pri = a.priorityScore - b.priorityScore;
  const mis = missedVal(a) - missedVal(b);
  const mat = matchVal(a) - matchVal(b);

  const orient = (diff: number) => (desc ? -diff : diff);

  if (sortKey === "priority") {
    if (pri !== 0) return orient(pri);
    if (mis !== 0) return orient(mis);
    return 0;
  }
  if (sortKey === "missedItc") {
    if (mis !== 0) return orient(mis);
    if (pri !== 0) return orient(pri);
    return 0;
  }
  if (mat !== 0) return orient(mat);
  return orient(pri);
}

function filterPortfolioRows(
  rows: ClientPortfolioRow[],
  filters: PortfolioFilters
): ClientPortfolioRow[] {
  const q = filters.search.trim().toLowerCase();
  return rows.filter((row) => {
    if (filters.assignedStaffId !== "ALL") {
      if (row.client.assignedStaffId !== filters.assignedStaffId) return false;
    }
    if (filters.period !== "ALL") {
      const p = row.latestRun?.period;
      if (p !== filters.period) return false;
    }
    if (!statusMatchesFilter(filters.status, row.latestRun)) return false;
    if (q) {
      const name = row.client.tradeName.toLowerCase();
      const gst = row.client.gstin.toLowerCase();
      if (!name.includes(q) && !gst.includes(q)) return false;
    }
    return true;
  });
}

export interface PortfolioQuery {
  page: number;
  limit: number;
  filters: PortfolioFilters;
  sort: { key: PortfolioSortKey; dir: SortDirection };
}

export function paginatePortfolio(
  rows: ClientPortfolioRow[],
  query: PortfolioQuery
): PaginatedPortfolioResponse {
  const filtered = filterPortfolioRows(rows, query.filters);
  const { key, dir } = query.sort;
  const sorted = [...filtered].sort((a, b) => comparePortfolioRows(a, b, key, dir));
  const total = sorted.length;
  const start = (query.page - 1) * query.limit;
  const data = sorted.slice(start, start + query.limit);
  return {
    data,
    total,
    page: query.page,
    limit: query.limit,
  };
}

export function derivePeriodLabels(runs: ReconcileRunListRow[]): string[] {
  const labels = new Set<string>();
  for (const r of runs) {
    labels.add(formatPeriodLabel(r.period));
  }
  return Array.from(labels).sort();
}

export function computeDashboardSignals(rows: ClientPortfolioRow[]): {
  failedClientCount: number;
  completeReadyCount: number;
  showAllFinalizedBanner: boolean;
} {
  const failedClientCount = rows.filter((r) => r.latestRun?.status === "FAILED")
    .length;
  const completeReadyCount = rows.filter((r) => r.latestRun?.status === "COMPLETE")
    .length;
  const showAllFinalizedBanner =
    rows.length > 0 &&
    failedClientCount === 0 &&
    completeReadyCount === 0 &&
    rows.every((r) => r.latestRun?.status === "FINALIZED");
  return { failedClientCount, completeReadyCount, showAllFinalizedBanner };
}

export function computeDashboardStats(
  clientsLen: number,
  runs: ReconcileRunListRow[],
  staffLen: number
): DashboardStats {
  let pendingThisMonth = 0;
  let totalItcProtected = 0;
  let itcProtectedHasData = false;
  for (const r of runs) {
    const ui = mapBackendRunStatus(r.status);
    if (ui === "PENDING" || ui === "IMPORTING" || ui === "MATCHING") {
      pendingThisMonth += 1;
    }
    if (ui === "FINALIZED") {
      const paise = matchedItcPaiseFromSummary(r.run_summary);
      if (paise != null) {
        itcProtectedHasData = true;
        const rupee = paiseToRupee(paise);
        if (rupee != null) totalItcProtected += rupee;
      }
    }
  }
  return {
    totalClients: clientsLen,
    pendingThisMonth,
    totalItcProtected,
    itcProtectedHasData,
    teamMembers: staffLen,
  };
}
