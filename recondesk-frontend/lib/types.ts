/**
 * Status machine — these are the ONLY valid statuses.
 * NOTE (display): COMPLETE means the matching engine finished (ready for review),
 * not that the user finalized/signed off. FINALIZED is set only after
 * "Finalize Reconciliation". UI labels map COMPLETE → "Ready for Review" and
 * FINALIZED → green "Complete"; do not rename these enum values without a
 * coordinated API/DB migration.
 */
export type ReconciliationStatus =
  | "PENDING"
  | "IMPORTING"
  | "MATCHING"
  | "COMPLETE"
  | "FINALIZED"
  | "FAILED";

export type ComplianceRisk = "LOW" | "MEDIUM" | "HIGH" | "CRITICAL";

export interface Staff {
  id: string;
  name: string;
  email: string;
  role: "ADMIN" | "STAFF";
  avatarInitials: string;
}

export interface Client {
  id: string;
  tradeName: string;
  gstin: string;
  registrationType: "Regular" | "Composition" | "SEZ";
  schemeType?: 'regular' | 'composition' | 'casual' | 'nrtp' | 'isd' | 'tds_tcs_deductor';
  filingFrequency?: 'monthly' | 'qrmp';
  assignedStaffId: string;
  createdAt: string;
  isDemo?: boolean;
}

export interface ReconciliationRun {
  id: string;
  clientId: string;
  period: string;
  runNumber: number;
  status: ReconciliationStatus;
  matchRate: number | null;
  itcClaimed: number | null;
  missedItc: number | null;
  complianceRisk: ComplianceRisk | null;
  errorMessage: string | null;
  finalizedBy: string | null;
  finalizedAt: string | null;
  createdAt: string;
  updatedAt: string;
}

export interface ClientPortfolioRow {
  client: Client;
  latestRun: ReconciliationRun | null;
  priorityScore: number;
  assignedStaff: Staff;
}

export interface DashboardStats {
  totalClients: number;
  pendingThisMonth: number;
  totalItcProtected: number;
  /** True when at least one finalized run has matched ITC in run_summary. */
  itcProtectedHasData: boolean;
  teamMembers: number;
}

export type PortfolioStatusFilter =
  | "ALL"
  | "PENDING"
  | "IN_PROGRESS"
  | "COMPLETE"
  | "FINALIZED"
  | "FAILED";

export interface PortfolioFilters {
  status: PortfolioStatusFilter;
  assignedStaffId: string | "ALL";
  period: string | "ALL";
  search: string;
}

export interface PaginatedPortfolioResponse {
  data: ClientPortfolioRow[];
  total: number;
  page: number;
  limit: number;
}

export interface ItcTrendPoint {
  period: string;
  missedItc: number;
}

export type SortDirection = "asc" | "desc";

export type PortfolioSortKey = "priority" | "matchRate" | "missedItc";
