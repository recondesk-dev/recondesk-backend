"use client";

import React, { useState, useEffect, useCallback } from "react";
import { useAccessToken } from "@/lib/hooks/useAccessToken";
import {
  practiceApi,
  type PracticeDashboardSummary,
  type PartnerGovernanceSummary,
  type PracticeOrganization,
} from "@/lib/api";
import { UnifiedFilingGrid } from "@/components/practice/UnifiedFilingGrid";
import { OrganizationFleet } from "@/components/practice/OrganizationFleet";
import { TaskBoard } from "@/components/practice/TaskBoard";
import { ComplianceCalendarView } from "@/components/practice/ComplianceCalendarView";
import { PartnerGovernanceView } from "@/components/practice/PartnerGovernanceView";
import { BulkOperationsModal } from "@/components/practice/BulkOperationsModal";
import {
  Building2,
  FileCheck2,
  CheckSquare,
  Calendar,
  ShieldAlert,
  Layers,
  RefreshCw,
  AlertTriangle,
  Loader2,
  Users,
  Clock,
  Sparkles,
} from "lucide-react";

export default function PracticeManagementPage() {
  const token = useAccessToken();
  const tokenLoading = token === null;

  // Tab State
  const [activeTab, setActiveTab] = useState<
    "FILING_FLEET" | "ORGANIZATIONS" | "TASKS" | "CALENDAR" | "GOVERNANCE"
  >("FILING_FLEET");

  // Filter & Data States
  const [period, setPeriod] = useState<string>("102026");
  const [dashboardData, setDashboardData] = useState<PracticeDashboardSummary | null>(null);
  const [governanceData, setGovernanceData] = useState<PartnerGovernanceSummary | null>(null);
  const [organizations, setOrganizations] = useState<PracticeOrganization[]>([]);
  const [loading, setLoading] = useState<boolean>(true);
  const [error, setError] = useState<string | null>(null);

  // Bulk Operations Modal
  const [bulkModalOpen, setBulkModalOpen] = useState<boolean>(false);

  const fetchData = useCallback(async () => {
    if (typeof token !== "string") return;
    setLoading(true);
    setError(null);
    try {
      const [dashRes, govRes, orgsRes] = await Promise.all([
        practiceApi.getDashboard(token, { period }),
        practiceApi.getPartnerGovernance(token),
        practiceApi.listOrganizations(token),
      ]);
      setDashboardData(dashRes);
      setGovernanceData(govRes);
      setOrganizations(orgsRes.organizations || []);
    } catch (err: any) {
      setError(err.message || "Failed to load practice management data");
    } finally {
      setLoading(false);
    }
  }, [token, period]);

  useEffect(() => {
    if (token) {
      fetchData();
    }
  }, [token, period, fetchData]);

  const summary = dashboardData?.summary;

  return (
    <div className="mx-auto max-w-7xl px-4 sm:px-6 lg:px-8 py-8 space-y-8">
      {/* Page Header */}
      <div className="flex flex-col md:flex-row md:items-center justify-between gap-4">
        <div>
          <div className="flex items-center gap-2">
            <h1 className="text-2xl font-bold tracking-tight text-gray-900">
              CA Firm Practice Command Center
            </h1>
            <span className="px-2 py-0.5 rounded-full text-[11px] font-bold bg-indigo-50 text-indigo-700 border border-indigo-200">
              Phase 3.4
            </span>
          </div>
          <p className="mt-1 text-xs text-gray-500">
            Multi-state PAN organizations, unified filing progress, maker-checker governance, and statutory compliance.
          </p>
        </div>

        {/* Global Action Toolbar */}
        <div className="flex flex-wrap items-center gap-3">
          {/* Period Selector */}
          <div className="flex items-center gap-1.5 text-xs bg-white border border-gray-200 rounded-lg px-2.5 py-1.5 shadow-sm">
            <span className="text-gray-500 font-medium">Period:</span>
            <input
              type="text"
              value={period}
              onChange={(e) => setPeriod(e.target.value)}
              placeholder="MMYYYY"
              className="w-16 font-mono font-semibold text-gray-800 bg-transparent focus:outline-none"
            />
          </div>

          {/* Bulk Operations Trigger */}
          <button
            type="button"
            onClick={() => setBulkModalOpen(true)}
            disabled={!token}
            className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-lg bg-indigo-600 text-white text-xs font-semibold shadow-sm hover:bg-indigo-700 disabled:opacity-50 transition"
          >
            <Layers className="w-3.5 h-3.5" />
            Bulk Operations
          </button>

          {/* Refresh Button */}
          <button
            type="button"
            onClick={fetchData}
            disabled={loading || !token}
            className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-lg bg-white border border-gray-200 text-gray-700 text-xs font-medium shadow-sm hover:bg-gray-50 disabled:opacity-50 transition"
          >
            <RefreshCw className={`w-3.5 h-3.5 ${loading ? "animate-spin" : ""}`} />
            Refresh
          </button>
        </div>
      </div>

      {/* Top Practice Metrics Grid */}
      <div className="grid grid-cols-2 sm:grid-cols-4 lg:grid-cols-8 gap-3">
        {/* Organizations */}
        <div className="p-3 rounded-xl bg-white border border-gray-200 shadow-sm">
          <div className="text-[11px] text-gray-500 font-medium truncate">Organizations</div>
          <div className="text-xl font-bold text-gray-900 mt-1">
            {summary?.total_organizations ?? "-"}
          </div>
          <div className="text-[10px] text-gray-400 mt-0.5">PAN entities</div>
        </div>

        {/* GSTINs */}
        <div className="p-3 rounded-xl bg-white border border-gray-200 shadow-sm">
          <div className="text-[11px] text-gray-500 font-medium truncate">Total GSTINs</div>
          <div className="text-xl font-bold text-gray-900 mt-1">
            {summary?.total_gstins ?? "-"}
          </div>
          <div className="text-[10px] text-gray-400 mt-0.5">Active branches</div>
        </div>

        {/* Filed */}
        <div className="p-3 rounded-xl bg-emerald-50/50 border border-emerald-200 shadow-sm">
          <div className="text-[11px] text-emerald-800 font-semibold truncate">Filed</div>
          <div className="text-xl font-bold text-emerald-700 mt-1">
            {summary?.total_filed ?? "-"}
          </div>
          <div className="text-[10px] text-emerald-600 mt-0.5">Verified GSTN</div>
        </div>

        {/* Ready to File */}
        <div className="p-3 rounded-xl bg-cyan-50/50 border border-cyan-200 shadow-sm">
          <div className="text-[11px] text-cyan-800 font-semibold truncate">Ready to File</div>
          <div className="text-xl font-bold text-cyan-700 mt-1">
            {summary?.total_ready_to_file ?? "-"}
          </div>
          <div className="text-[10px] text-cyan-600 mt-0.5">Gates approved</div>
        </div>

        {/* Maker-Checker */}
        <div className="p-3 rounded-xl bg-amber-50/50 border border-amber-200 shadow-sm">
          <div className="text-[11px] text-amber-800 font-semibold truncate">Under Review</div>
          <div className="text-xl font-bold text-amber-700 mt-1">
            {summary?.pending_maker_checker_review ?? "-"}
          </div>
          <div className="text-[10px] text-amber-600 mt-0.5">Maker-Checker</div>
        </div>

        {/* Client Consent */}
        <div className="p-3 rounded-xl bg-indigo-50/50 border border-indigo-200 shadow-sm">
          <div className="text-[11px] text-indigo-800 font-semibold truncate">Client Consent</div>
          <div className="text-xl font-bold text-indigo-700 mt-1">
            {summary?.pending_client_consent ?? "-"}
          </div>
          <div className="text-[10px] text-indigo-600 mt-0.5">Awaiting auth</div>
        </div>

        {/* Blocked */}
        <div className="p-3 rounded-xl bg-rose-50/50 border border-rose-200 shadow-sm">
          <div className="text-[11px] text-rose-800 font-semibold truncate">Blocked</div>
          <div className="text-xl font-bold text-rose-700 mt-1">
            {summary?.blocked_count ?? "-"}
          </div>
          <div className="text-[10px] text-rose-600 mt-0.5">Action needed</div>
        </div>

        {/* Open Tasks */}
        <div className="p-3 rounded-xl bg-white border border-gray-200 shadow-sm">
          <div className="text-[11px] text-gray-500 font-medium truncate">Open Tasks</div>
          <div className="text-xl font-bold text-gray-900 mt-1">
            {summary?.open_tasks_count ?? "-"}
          </div>
          <div className="text-[10px] text-gray-400 mt-0.5">Staff backlog</div>
        </div>
      </div>

      {/* Primary Tab Navigation */}
      <div className="flex border-b border-gray-200 bg-white px-2 rounded-t-xl">
        <button
          type="button"
          onClick={() => setActiveTab("FILING_FLEET")}
          className={`py-3 px-4 text-xs font-semibold border-b-2 transition flex items-center gap-2 ${
            activeTab === "FILING_FLEET"
              ? "border-indigo-600 text-indigo-600"
              : "border-transparent text-gray-500 hover:text-gray-700"
          }`}
        >
          <FileCheck2 className="w-4 h-4" />
          Filing Progress Fleet
        </button>

        <button
          type="button"
          onClick={() => setActiveTab("ORGANIZATIONS")}
          className={`py-3 px-4 text-xs font-semibold border-b-2 transition flex items-center gap-2 ${
            activeTab === "ORGANIZATIONS"
              ? "border-indigo-600 text-indigo-600"
              : "border-transparent text-gray-500 hover:text-gray-700"
          }`}
        >
          <Building2 className="w-4 h-4" />
          PAN Organizations
        </button>

        <button
          type="button"
          onClick={() => setActiveTab("TASKS")}
          className={`py-3 px-4 text-xs font-semibold border-b-2 transition flex items-center gap-2 ${
            activeTab === "TASKS"
              ? "border-indigo-600 text-indigo-600"
              : "border-transparent text-gray-500 hover:text-gray-700"
          }`}
        >
          <CheckSquare className="w-4 h-4" />
          Staff Tasks &amp; Workflow
        </button>

        <button
          type="button"
          onClick={() => setActiveTab("CALENDAR")}
          className={`py-3 px-4 text-xs font-semibold border-b-2 transition flex items-center gap-2 ${
            activeTab === "CALENDAR"
              ? "border-indigo-600 text-indigo-600"
              : "border-transparent text-gray-500 hover:text-gray-700"
          }`}
        >
          <Calendar className="w-4 h-4" />
          Compliance Calendar
        </button>

        <button
          type="button"
          onClick={() => setActiveTab("GOVERNANCE")}
          className={`py-3 px-4 text-xs font-semibold border-b-2 transition flex items-center gap-2 ${
            activeTab === "GOVERNANCE"
              ? "border-indigo-600 text-indigo-600"
              : "border-transparent text-gray-500 hover:text-gray-700"
          }`}
        >
          <ShieldAlert className="w-4 h-4" />
          Partner Governance
        </button>
      </div>

      {/* Main Tab Content */}
      <div className="space-y-6">
        {error && (
          <div className="p-4 rounded-xl bg-rose-50 border border-rose-200 text-xs text-rose-700 flex items-center gap-2.5">
            <AlertTriangle className="w-4 h-4 shrink-0" />
            <span>{error}</span>
          </div>
        )}

        {loading && !dashboardData ? (
          <div className="text-center py-20 bg-white rounded-xl border border-gray-200">
            <Loader2 className="w-8 h-8 text-indigo-600 animate-spin mx-auto mb-2" />
            <p className="text-xs font-medium text-gray-500">Loading CA practice fleet data...</p>
          </div>
        ) : (
          <>
            {/* TAB 1: FILING PROGRESS FLEET */}
            {activeTab === "FILING_FLEET" && (
              <UnifiedFilingGrid
                rows={dashboardData?.filing_grid || []}
                period={period}
                onRefresh={fetchData}
              />
            )}

            {/* TAB 2: PAN ORGANIZATIONS */}
            {activeTab === "ORGANIZATIONS" && (
              <OrganizationFleet
                organizations={organizations}
                token={token || ""}
                onRefresh={fetchData}
              />
            )}

            {/* TAB 3: TASKS BOARD */}
            {activeTab === "TASKS" && (
              <TaskBoard
                tasks={dashboardData?.tasks || []}
                token={token || ""}
                organizations={organizations}
                onRefresh={fetchData}
              />
            )}

            {/* TAB 4: COMPLIANCE CALENDAR */}
            {activeTab === "CALENDAR" && (
              <ComplianceCalendarView
                deadlines={dashboardData?.calendar || []}
                selectedPeriod={period}
                onSelectPeriod={(p) => setPeriod(p)}
                onRefresh={fetchData}
              />
            )}

            {/* TAB 5: PARTNER GOVERNANCE */}
            {activeTab === "GOVERNANCE" && governanceData && (
              <PartnerGovernanceView
                data={governanceData}
                onRefresh={fetchData}
              />
            )}
          </>
        )}
      </div>

      {/* Bulk Operations Modal */}
      {typeof token === "string" && (
        <BulkOperationsModal
          open={bulkModalOpen}
          onClose={() => setBulkModalOpen(false)}
          token={token}
          organizations={organizations}
          onSuccess={() => {
            fetchData();
          }}
        />
      )}
    </div>
  );
}
