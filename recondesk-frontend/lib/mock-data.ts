import { computePriorityScore } from "./priority";
import type {
  Client,
  ClientPortfolioRow,
  DashboardStats,
  ItcTrendPoint,
  PaginatedPortfolioResponse,
  PortfolioFilters,
  PortfolioSortKey,
  PortfolioStatusFilter,
  ReconciliationRun,
  SortDirection,
  Staff,
} from "./types";

const delay = (ms: number) => new Promise((r) => setTimeout(r, ms));

const MOCK_DELAY_MS = 400;

export const INITIAL_STAFF: Staff[] = [
  {
    id: "staff-priya",
    name: "Priya Sharma",
    email: "priya.sharma@recondesk.in",
    role: "ADMIN",
    avatarInitials: "PS",
  },
  {
    id: "staff-rahul",
    name: "Rahul Nair",
    email: "rahul.nair@recondesk.in",
    role: "STAFF",
    avatarInitials: "RN",
  },
  {
    id: "staff-sneha",
    name: "Sneha Patil",
    email: "sneha.patil@recondesk.in",
    role: "STAFF",
    avatarInitials: "SP",
  },
];

const BASE_CLIENTS: Client[] = [
  {
    id: "client-zenith",
    tradeName: "Zenith Polymers Pvt Ltd",
    gstin: "27AABCU9603R1Z2",
    registrationType: "Regular",
    assignedStaffId: "staff-priya",
    createdAt: "2024-06-12T10:00:00.000Z",
  },
  {
    id: "client-krishna",
    tradeName: "Krishna Foods & Spices",
    gstin: "27AADCB2230M1ZX",
    registrationType: "Regular",
    assignedStaffId: "staff-rahul",
    createdAt: "2024-08-01T09:30:00.000Z",
  },
  {
    id: "client-sai",
    tradeName: "Sai Enterprises (Mumbai)",
    gstin: "27AAACR5055K1Z1",
    registrationType: "Composition",
    assignedStaffId: "staff-sneha",
    createdAt: "2024-05-20T14:15:00.000Z",
  },
  {
    id: "client-milind",
    tradeName: "Milind Logistics LLP",
    gstin: "27AAAFM1234N1Z9",
    registrationType: "Regular",
    assignedStaffId: "staff-priya",
    createdAt: "2024-09-10T11:00:00.000Z",
  },
  {
    id: "client-aurora",
    tradeName: "Aurora Textiles Ltd",
    gstin: "27AABCT7890P1Z3",
    registrationType: "Regular",
    assignedStaffId: "staff-rahul",
    createdAt: "2024-07-22T08:45:00.000Z",
  },
  {
    id: "client-nexus",
    tradeName: "Nexus IT Solutions Pvt Ltd",
    gstin: "27AAACN4455Q1Z7",
    registrationType: "SEZ",
    assignedStaffId: "staff-sneha",
    createdAt: "2024-10-05T16:20:00.000Z",
  },
  {
    id: "client-bharat",
    tradeName: "Bharat Steel Traders",
    gstin: "27AAABB1122R1Z4",
    registrationType: "Regular",
    assignedStaffId: "staff-priya",
    createdAt: "2024-04-18T12:00:00.000Z",
  },
  {
    id: "client-laxmi",
    tradeName: "Laxmi General Stores",
    gstin: "27AAALG5566S1Z8",
    registrationType: "Composition",
    assignedStaffId: "staff-rahul",
    createdAt: "2024-11-01T09:00:00.000Z",
  },
  {
    id: "client-velocity",
    tradeName: "Velocity Auto Parts",
    gstin: "27AAAVC8899T1Z1",
    registrationType: "Regular",
    assignedStaffId: "staff-sneha",
    createdAt: "2024-03-14T13:30:00.000Z",
  },
  {
    id: "client-pinnacle",
    tradeName: "Pinnacle Pharma Distributors",
    gstin: "27AAAPP3344U1Z6",
    registrationType: "Regular",
    assignedStaffId: "staff-priya",
    createdAt: "2024-12-08T10:10:00.000Z",
  },
];

const BASE_RUNS: ReconciliationRun[] = [
  {
    id: "run-krishna-fail",
    clientId: "client-krishna",
    period: "Mar 2025",
    runNumber: 3,
    status: "FAILED",
    matchRate: null,
    itcClaimed: null,
    missedItc: null,
    complianceRisk: "HIGH",
    errorMessage: "GSTR-2B ingestion timed out after 3 retries. Check portal connectivity.",
    finalizedBy: null,
    finalizedAt: null,
    createdAt: "2025-04-10T08:00:00.000Z",
    updatedAt: "2025-04-10T08:05:00.000Z",
  },
  {
    id: "run-sai-final",
    clientId: "client-sai",
    period: "Feb 2025",
    runNumber: 2,
    status: "FINALIZED",
    matchRate: 94,
    itcClaimed: 18_45_000,
    missedItc: 12_000,
    complianceRisk: "LOW",
    errorMessage: null,
    finalizedBy: "Priya Sharma",
    finalizedAt: "2025-03-28T14:00:00.000Z",
    createdAt: "2025-03-15T10:00:00.000Z",
    updatedAt: "2025-03-28T14:00:00.000Z",
  },
  {
    id: "run-milind-complete",
    clientId: "client-milind",
    period: "Mar 2025",
    runNumber: 1,
    status: "COMPLETE",
    matchRate: 88,
    itcClaimed: 9_20_500,
    missedItc: 1_45_000,
    complianceRisk: "MEDIUM",
    errorMessage: null,
    finalizedBy: null,
    finalizedAt: null,
    createdAt: "2025-04-08T11:00:00.000Z",
    updatedAt: "2025-04-09T09:30:00.000Z",
  },
  {
    id: "run-aurora-complete",
    clientId: "client-aurora",
    period: "Mar 2025",
    runNumber: 4,
    status: "COMPLETE",
    matchRate: 92,
    itcClaimed: 22_10_000,
    missedItc: 68_000,
    complianceRisk: "LOW",
    errorMessage: null,
    finalizedBy: null,
    finalizedAt: null,
    createdAt: "2025-04-07T07:00:00.000Z",
    updatedAt: "2025-04-08T16:00:00.000Z",
  },
  {
    id: "run-nexus-match",
    clientId: "client-nexus",
    period: "Mar 2025",
    runNumber: 2,
    status: "MATCHING",
    matchRate: null,
    itcClaimed: null,
    missedItc: null,
    complianceRisk: null,
    errorMessage: null,
    finalizedBy: null,
    finalizedAt: null,
    createdAt: "2025-04-11T06:00:00.000Z",
    updatedAt: "2025-04-11T06:15:00.000Z",
  },
  {
    id: "run-bharat-match",
    clientId: "client-bharat",
    period: "Mar 2025",
    runNumber: 5,
    status: "MATCHING",
    matchRate: null,
    itcClaimed: null,
    missedItc: null,
    complianceRisk: null,
    errorMessage: null,
    finalizedBy: null,
    finalizedAt: null,
    createdAt: "2025-04-11T05:30:00.000Z",
    updatedAt: "2025-04-11T05:45:00.000Z",
  },
  {
    id: "run-laxmi-pending",
    clientId: "client-laxmi",
    period: "Mar 2025",
    runNumber: 1,
    status: "PENDING",
    matchRate: null,
    itcClaimed: null,
    missedItc: null,
    complianceRisk: null,
    errorMessage: null,
    finalizedBy: null,
    finalizedAt: null,
    createdAt: "2025-04-01T09:00:00.000Z",
    updatedAt: "2025-04-01T09:00:00.000Z",
  },
  {
    id: "run-velocity-pending",
    clientId: "client-velocity",
    period: "Mar 2025",
    runNumber: 3,
    status: "PENDING",
    matchRate: null,
    itcClaimed: null,
    missedItc: null,
    complianceRisk: null,
    errorMessage: null,
    finalizedBy: null,
    finalizedAt: null,
    createdAt: "2025-04-02T10:00:00.000Z",
    updatedAt: "2025-04-02T10:00:00.000Z",
  },
  {
    id: "run-pinnacle-import",
    clientId: "client-pinnacle",
    period: "Mar 2025",
    runNumber: 2,
    status: "FAILED",
    matchRate: null,
    itcClaimed: null,
    missedItc: null,
    complianceRisk: null,
    errorMessage:
      "GSTR-2B JSON parsing failed: unexpected token at line 847",
    finalizedBy: null,
    finalizedAt: null,
    createdAt: "2025-04-11T04:00:00.000Z",
    updatedAt: "2025-04-11T04:12:00.000Z",
  },
  {
    id: "run-milind-old",
    clientId: "client-milind",
    period: "Feb 2025",
    runNumber: 0,
    status: "FINALIZED",
    matchRate: 91,
    itcClaimed: 8_50_000,
    missedItc: 0,
    complianceRisk: "LOW",
    errorMessage: null,
    finalizedBy: "Rahul Nair",
    finalizedAt: "2025-03-10T12:00:00.000Z",
    createdAt: "2025-03-01T09:00:00.000Z",
    updatedAt: "2025-03-10T12:00:00.000Z",
  },
  {
    id: "run-aurora-old",
    clientId: "client-aurora",
    period: "Feb 2025",
    runNumber: 3,
    status: "FINALIZED",
    matchRate: 89,
    itcClaimed: 19_00_000,
    missedItc: 2_40_000,
    complianceRisk: "CRITICAL",
    errorMessage: null,
    finalizedBy: "Priya Sharma",
    finalizedAt: "2025-03-25T11:00:00.000Z",
    createdAt: "2025-03-05T08:00:00.000Z",
    updatedAt: "2025-03-25T11:00:00.000Z",
  },
];

function clone<T>(x: T): T {
  return JSON.parse(JSON.stringify(x)) as T;
}

let mockClients: Client[] = clone(BASE_CLIENTS);
let mockRuns: ReconciliationRun[] = clone(BASE_RUNS);

const ITC_TREND_SEED: Record<string, ItcTrendPoint[]> = {};

function buildTrendForClient(clientId: string): ItcTrendPoint[] {
  const months = [
    "Nov 2024",
    "Dec 2024",
    "Jan 2025",
    "Feb 2025",
    "Mar 2025",
    "Apr 2025",
  ];
  let seed = clientId.split("").reduce((a, c) => a + c.charCodeAt(0), 0);
  return months.map((period) => {
    seed = (seed * 9301 + 49297) % 233280;
    const v = Math.floor((seed / 233280) * 185000) + 8000;
    return { period, missedItc: period === "Apr 2025" ? Math.floor(v * 0.85) : v };
  });
}

for (const c of BASE_CLIENTS) {
  ITC_TREND_SEED[c.id] = buildTrendForClient(c.id);
}

function staffById(id: string): Staff {
  const s = INITIAL_STAFF.find((x) => x.id === id);
  if (!s) throw new Error(`Unknown staff: ${id}`);
  return s;
}

export function latestRunForClient(clientId: string): ReconciliationRun | null {
  const runs = mockRuns.filter((r) => r.clientId === clientId);
  if (runs.length === 0) return null;
  return runs.reduce((a, b) =>
    new Date(a.createdAt) >= new Date(b.createdAt) ? a : b
  );
}

export function buildPortfolioRow(client: Client): ClientPortfolioRow {
  const latestRun = latestRunForClient(client.id);
  return {
    client,
    latestRun,
    priorityScore: computePriorityScore(latestRun),
    assignedStaff: staffById(client.assignedStaffId),
  };
}

function statusMatchesFilter(
  status: PortfolioStatusFilter,
  run: ReconciliationRun | null
): boolean {
  if (status === "ALL") return true;
  if (!run) return status === "PENDING";
  const s = run.status;
  switch (status) {
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

export function getDistinctPeriods(): string[] {
  const set = new Set<string>();
  for (const r of mockRuns) set.add(r.period);
  return Array.from(set).sort();
}

export function computeDashboardSignals(): {
  failedClientCount: number;
  completeReadyCount: number;
  showAllFinalizedBanner: boolean;
} {
  const rows = mockClients.map((c) => buildPortfolioRow(c));
  const failedClientCount = rows.filter((r) => r.latestRun?.status === "FAILED").length;
  const completeReadyCount = rows.filter((r) => r.latestRun?.status === "COMPLETE").length;
  const showAllFinalizedBanner =
    mockClients.length > 0 &&
    failedClientCount === 0 &&
    completeReadyCount === 0 &&
    rows.every((r) => r.latestRun?.status === "FINALIZED");
  return { failedClientCount, completeReadyCount, showAllFinalizedBanner };
}

export function computeDashboardStats(): DashboardStats {
  const totalClients = mockClients.length;
  const pendingThisMonth = mockRuns.filter((r) =>
    ["PENDING", "IMPORTING", "MATCHING"].includes(r.status)
  ).length;
  const finalized = mockRuns.filter((r) => r.status === "FINALIZED");
  const totalItcProtected = finalized.reduce(
    (sum, r) => sum + (r.itcClaimed ?? 0),
    0
  );
  return {
    totalClients,
    pendingThisMonth,
    totalItcProtected,
    itcProtectedHasData: finalized.some((r) => r.itcClaimed != null),
    teamMembers: INITIAL_STAFF.length,
  };
}

export function countFailedRuns(): number {
  return mockRuns.filter((r) => r.status === "FAILED").length;
}

export function getFailedRunSummaries(): {
  clientId: string;
  tradeName: string;
  period: string;
  errorSnippet: string;
  runId: string;
}[] {
  return mockRuns
    .filter((r) => r.status === "FAILED")
    .map((r) => {
      const c = mockClients.find((x) => x.id === r.clientId);
      return {
        runId: r.id,
        clientId: r.clientId,
        tradeName: c?.tradeName ?? "Unknown",
        period: r.period,
        errorSnippet: (r.errorMessage ?? "").slice(0, 80),
      };
    });
}

export function addMockClient(client: Client): void {
  mockClients.push(client);
  ITC_TREND_SEED[client.id] = buildTrendForClient(client.id);
}

export function deleteMockClient(clientId: string): void {
  mockClients = mockClients.filter((c) => c.id !== clientId);
  mockRuns = mockRuns.filter((r) => r.clientId !== clientId);
  delete ITC_TREND_SEED[clientId];
}

export function updateMockClient(clientId: string, patch: Partial<Client>): void {
  mockClients = mockClients.map((c) =>
    c.id === clientId ? { ...c, ...patch } : c
  );
}

export function patchRun(runId: string, patch: Partial<ReconciliationRun>): void {
  mockRuns = mockRuns.map((r) =>
    r.id === runId ? { ...r, ...patch, updatedAt: new Date().toISOString() } : r
  );
}

export function retryFailedRun(runId: string): void {
  patchRun(runId, {
    status: "IMPORTING",
    errorMessage: null,
    matchRate: null,
    itcClaimed: null,
    missedItc: null,
    complianceRisk: null,
  });
}

export function finalizeRun(
  runId: string,
  finalizedBy: string
): void {
  const run = mockRuns.find((r) => r.id === runId);
  if (!run || run.status !== "COMPLETE") return;
  patchRun(runId, {
    status: "FINALIZED",
    finalizedBy,
    finalizedAt: new Date().toISOString(),
  });
}

export function assignStaffToClients(clientIds: string[], staffId: string): void {
  mockClients = mockClients.map((c) =>
    clientIds.includes(c.id) ? { ...c, assignedStaffId: staffId } : c
  );
}

export function bulkFinalizeCompleteRuns(clientIds: string[]): void {
  for (const cid of clientIds) {
    const run = latestRunForClient(cid);
    if (run?.status === "COMPLETE") {
      finalizeRun(run.id, "Priya Sharma");
    }
  }
}

export function bulkRetryFailedForClients(clientIds: string[]): void {
  for (const cid of clientIds) {
    const run = latestRunForClient(cid);
    if (run?.status === "FAILED") retryFailedRun(run.id);
  }
}

export function areAllSelectedComplete(clientIds: string[]): boolean {
  if (clientIds.length === 0) return false;
  return clientIds.every((id) => latestRunForClient(id)?.status === "COMPLETE");
}

export function areAllSelectedFailed(clientIds: string[]): boolean {
  if (clientIds.length === 0) return false;
  return clientIds.every((id) => latestRunForClient(id)?.status === "FAILED");
}

export interface ClientManagementRow {
  client: Client;
  runCount: number;
  lastRun: ReconciliationRun | null;
}

export function getClientManagementRows(): ClientManagementRow[] {
  return mockClients.map((c) => {
    const runs = mockRuns.filter((r) => r.clientId === c.id);
    const last =
      runs.length === 0
        ? null
        : runs.reduce((a, b) => (new Date(a.createdAt) >= new Date(b.createdAt) ? a : b));
    return { client: c, runCount: runs.length, lastRun: last };
  });
}

export function resetMockData(): void {
  mockClients = clone(BASE_CLIENTS);
  mockRuns = clone(BASE_RUNS);
  for (const c of BASE_CLIENTS) {
    ITC_TREND_SEED[c.id] = buildTrendForClient(c.id);
  }
}

export interface PortfolioQuery {
  page: number;
  limit: number;
  filters: PortfolioFilters;
  sort: { key: PortfolioSortKey; dir: SortDirection };
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

export function fetchPortfolioPage(query: PortfolioQuery): PaginatedPortfolioResponse {
  const allRows = mockClients.map((c) => buildPortfolioRow(c));
  const filtered = filterPortfolioRows(allRows, query.filters);
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

export const mockFetchers = {
  "/api/dashboard/stats": async (): Promise<DashboardStats> => {
    await delay(MOCK_DELAY_MS);
    return computeDashboardStats();
  },

  "/api/clients": async (): Promise<Client[]> => {
    await delay(MOCK_DELAY_MS);
    return clone(mockClients);
  },

  "/api/clients/management": async (): Promise<ClientManagementRow[]> => {
    await delay(MOCK_DELAY_MS);
    return clone(getClientManagementRows());
  },

  "/api/portfolio": async (query: PortfolioQuery): Promise<PaginatedPortfolioResponse> => {
    await delay(MOCK_DELAY_MS);
    return fetchPortfolioPage(query);
  },

  "/api/clients/[id]": async (id: string): Promise<Client> => {
    await delay(MOCK_DELAY_MS);
    const c = mockClients.find((x) => x.id === id);
    if (!c) throw new Error("Client not found");
    return clone(c);
  },

  "/api/clients/[id]/runs": async (id: string): Promise<ReconciliationRun[]> => {
    await delay(MOCK_DELAY_MS);
    return clone(
      mockRuns
        .filter((r) => r.clientId === id)
        .sort((a, b) => new Date(b.createdAt).getTime() - new Date(a.createdAt).getTime())
    );
  },

  "/api/staff": async (): Promise<Staff[]> => {
    await delay(MOCK_DELAY_MS);
    return clone(INITIAL_STAFF);
  },

  "/api/clients/[id]/itc-trend": async (id: string): Promise<ItcTrendPoint[]> => {
    await delay(MOCK_DELAY_MS);
    return clone(ITC_TREND_SEED[id] ?? buildTrendForClient(id));
  },

  "/api/dashboard/failures": async (): Promise<{
    count: number;
    items: ReturnType<typeof getFailedRunSummaries>;
  }> => {
    await delay(MOCK_DELAY_MS);
    return { count: countFailedRuns(), items: getFailedRunSummaries() };
  },

  "/api/dashboard/signals": async (): Promise<ReturnType<typeof computeDashboardSignals>> => {
    await delay(MOCK_DELAY_MS);
    return computeDashboardSignals();
  },

  "/api/periods": async (): Promise<string[]> => {
    await delay(MOCK_DELAY_MS);
    return getDistinctPeriods();
  },
};

/** Force error for testing SWR error UI when id === "__error__" */
export function shouldSimulatePortfolioError(): boolean {
  return false;
}
