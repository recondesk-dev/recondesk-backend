"use client";

import React from "react";
import Link from "next/link";
import {
  type PartnerGovernanceSummary,
  type PracticeTask,
} from "@/lib/api";
import {
  ShieldAlert,
  CheckCircle2,
  Clock,
  AlertTriangle,
  ArrowRight,
  UserCheck,
  FileText,
  AlertOctagon,
  Scale,
} from "lucide-react";

interface Props {
  data: PartnerGovernanceSummary;
  onRefresh?: () => void;
}

export function PartnerGovernanceView({ data, onRefresh }: Props) {
  const {
    pending_maker_checker_approvals = [],
    pending_maker_checker_count = 0,
    blocked_tasks = [],
    blocked_tasks_count = 0,
    overdue_tasks = [],
    overdue_tasks_count = 0,
    recent_governance_overrides = [],
  } = data;

  return (
    <div className="space-y-6">
      {/* Metric Cards Banner */}
      <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4">
        {/* Pending Approvals */}
        <div className="p-4 rounded-xl border border-amber-200 bg-amber-50/40">
          <div className="flex items-center justify-between">
            <span className="text-xs font-semibold text-amber-800">
              Pending Maker-Checker
            </span>
            <UserCheck className="w-4 h-4 text-amber-600" />
          </div>
          <div className="mt-2 flex items-baseline gap-2">
            <span className="text-2xl font-bold text-amber-950">
              {pending_maker_checker_count}
            </span>
            <span className="text-xs text-amber-700">awaiting review</span>
          </div>
          <p className="mt-1 text-xs text-amber-600/90">
            Requires Manager / Partner approval
          </p>
        </div>

        {/* Blocked Tasks */}
        <div className="p-4 rounded-xl border border-rose-200 bg-rose-50/40">
          <div className="flex items-center justify-between">
            <span className="text-xs font-semibold text-rose-800">
              Blocked Workflows
            </span>
            <AlertOctagon className="w-4 h-4 text-rose-600" />
          </div>
          <div className="mt-2 flex items-baseline gap-2">
            <span className="text-2xl font-bold text-rose-950">
              {blocked_tasks_count}
            </span>
            <span className="text-xs text-rose-700">action required</span>
          </div>
          <p className="mt-1 text-xs text-rose-600/90">
            Client data or reconciliations stuck
          </p>
        </div>

        {/* Overdue Tasks */}
        <div className="p-4 rounded-xl border border-orange-200 bg-orange-50/40">
          <div className="flex items-center justify-between">
            <span className="text-xs font-semibold text-orange-800">
              Overdue Tasks
            </span>
            <Clock className="w-4 h-4 text-orange-600" />
          </div>
          <div className="mt-2 flex items-baseline gap-2">
            <span className="text-2xl font-bold text-orange-950">
              {overdue_tasks_count}
            </span>
            <span className="text-xs text-orange-700">past deadline</span>
          </div>
          <p className="mt-1 text-xs text-orange-600/90">
            Statutory deadline risk
          </p>
        </div>

        {/* Governance Overrides */}
        <div className="p-4 rounded-xl border border-purple-200 bg-purple-50/40">
          <div className="flex items-center justify-between">
            <span className="text-xs font-semibold text-purple-800">
              Partner Overrides
            </span>
            <Scale className="w-4 h-4 text-purple-600" />
          </div>
          <div className="mt-2 flex items-baseline gap-2">
            <span className="text-2xl font-bold text-purple-950">
              {recent_governance_overrides.length}
            </span>
            <span className="text-xs text-purple-700">active statutory</span>
          </div>
          <p className="mt-1 text-xs text-purple-600/90">
            Atomic rule compliance overrides
          </p>
        </div>
      </div>

      {/* Governance Notice */}
      <div className="p-4 rounded-xl bg-slate-900 text-white flex items-start gap-3">
        <ShieldAlert className="w-5 h-5 text-amber-400 shrink-0 mt-0.5" />
        <div className="text-xs leading-relaxed space-y-1">
          <span className="font-semibold text-amber-300">
            Statutory Governance & Separation of Duties Invariant:
          </span>
          <p className="text-slate-300">
            Under Section 3.2 Maker-Checker rules, the preparer of a return may not approve their own submission.
            Filing approval locks return figures to their deterministic SHA-256 digest. Maker-checker approval never
            substitutes for required statutory compliance overrides.
          </p>
        </div>
      </div>

      {/* Grid: Pending Approvals & Blocked Tasks */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
        {/* Pending Approvals Queue */}
        <div className="rounded-xl border border-gray-200 bg-white shadow-sm overflow-hidden flex flex-col">
          <div className="px-5 py-4 border-b border-gray-100 flex items-center justify-between bg-gray-50/50">
            <div>
              <h3 className="text-sm font-bold text-gray-900 flex items-center gap-2">
                <UserCheck className="w-4 h-4 text-amber-600" />
                Pending Maker-Checker Approvals
              </h3>
              <p className="text-xs text-gray-500 mt-0.5">
                Submitted returns awaiting Manager or Partner review
              </p>
            </div>
            <span className="px-2 py-0.5 text-xs font-semibold rounded-full bg-amber-100 text-amber-800">
              {pending_maker_checker_count}
            </span>
          </div>

          <div className="p-5 flex-1 divide-y divide-gray-100">
            {pending_maker_checker_approvals.length === 0 ? (
              <div className="text-center py-8">
                <CheckCircle2 className="w-8 h-8 text-emerald-500 mx-auto mb-2" />
                <p className="text-sm font-medium text-gray-700">No approvals pending</p>
                <p className="text-xs text-gray-400 mt-0.5">All submitted returns have been reviewed.</p>
              </div>
            ) : (
              pending_maker_checker_approvals.map((appr: any, idx: number) => {
                const returnType = appr.return_type || "GSTR-1";
                const reviewUrl =
                  returnType === "GSTR-3B"
                    ? `/filing/gstr-3b?gstin_id=${appr.client_gstin_id}&period=${appr.return_period}`
                    : `/filing/gstr-1?gstin_id=${appr.client_gstin_id}&period=${appr.return_period}`;

                return (
                  <div key={appr.id || idx} className="py-3 first:pt-0 last:pb-0 flex items-center justify-between gap-3">
                    <div className="min-w-0">
                      <div className="flex items-center gap-2">
                        <span className="font-semibold text-xs text-gray-900 font-mono">
                          {appr.gstin || "GSTIN"}
                        </span>
                        <span className="px-1.5 py-0.5 text-[10px] font-bold rounded bg-indigo-50 text-indigo-700">
                          {returnType}
                        </span>
                        <span className="text-xs text-gray-500 font-mono">
                          {appr.return_period}
                        </span>
                      </div>
                      <div className="mt-1 flex items-center gap-2 text-xs text-gray-500">
                        <span>Prepared by: <strong className="text-gray-700">{appr.preparer_name || appr.preparer_id || "Preparer"}</strong></span>
                        {appr.submitted_at && (
                          <span>&bull; {new Date(appr.submitted_at).toLocaleDateString()}</span>
                        )}
                      </div>
                      {appr.figures_digest && (
                        <div className="mt-1 font-mono text-[10px] text-gray-400 truncate max-w-xs">
                          SHA: {appr.figures_digest.slice(0, 16)}...
                        </div>
                      )}
                    </div>

                    <Link
                      href={reviewUrl}
                      className="shrink-0 inline-flex items-center gap-1 px-3 py-1.5 text-xs font-semibold rounded-lg bg-indigo-600 text-white hover:bg-indigo-700 transition"
                    >
                      Review
                      <ArrowRight className="w-3.5 h-3.5" />
                    </Link>
                  </div>
                );
              })
            )}
          </div>
        </div>

        {/* Blocked Tasks */}
        <div className="rounded-xl border border-gray-200 bg-white shadow-sm overflow-hidden flex flex-col">
          <div className="px-5 py-4 border-b border-gray-100 flex items-center justify-between bg-gray-50/50">
            <div>
              <h3 className="text-sm font-bold text-gray-900 flex items-center gap-2">
                <AlertOctagon className="w-4 h-4 text-rose-600" />
                Blocked Tasks &amp; Exceptions
              </h3>
              <p className="text-xs text-gray-500 mt-0.5">
                Staff tasks marked BLOCKED requiring intervention
              </p>
            </div>
            <span className="px-2 py-0.5 text-xs font-semibold rounded-full bg-rose-100 text-rose-800">
              {blocked_tasks_count}
            </span>
          </div>

          <div className="p-5 flex-1 divide-y divide-gray-100">
            {blocked_tasks.length === 0 ? (
              <div className="text-center py-8">
                <CheckCircle2 className="w-8 h-8 text-emerald-500 mx-auto mb-2" />
                <p className="text-sm font-medium text-gray-700">No blocked tasks</p>
                <p className="text-xs text-gray-400 mt-0.5">Practice workflows are moving forward cleanly.</p>
              </div>
            ) : (
              blocked_tasks.map((task: PracticeTask) => (
                <div key={task.id} className="py-3 first:pt-0 last:pb-0">
                  <div className="flex items-start justify-between gap-2">
                    <div>
                      <h4 className="text-xs font-bold text-gray-900">{task.title}</h4>
                      <p className="text-xs text-gray-500 mt-0.5">
                        {task.description || "No blocker details provided"}
                      </p>
                    </div>
                    <span className="px-2 py-0.5 rounded text-[10px] font-bold bg-rose-100 text-rose-700 border border-rose-200">
                      {task.priority}
                    </span>
                  </div>
                  <div className="mt-2 flex items-center justify-between text-xs text-gray-500">
                    <span>Category: <strong>{task.category}</strong></span>
                    {task.due_date && <span>Due: {task.due_date}</span>}
                  </div>
                </div>
              ))
            )}
          </div>
        </div>
      </div>

      {/* Statutory Overrides Log */}
      <div className="rounded-xl border border-gray-200 bg-white shadow-sm overflow-hidden">
        <div className="px-5 py-4 border-b border-gray-100 bg-gray-50/50">
          <h3 className="text-sm font-bold text-gray-900 flex items-center gap-2">
            <Scale className="w-4 h-4 text-purple-600" />
            Statutory Compliance Overrides Log
          </h3>
          <p className="text-xs text-gray-500 mt-0.5">
            Immutable audit record of Partner-level statutory check overrides (Phase 2 Governance)
          </p>
        </div>

        <div className="p-5">
          {recent_governance_overrides.length === 0 ? (
            <div className="text-center py-6 text-xs text-gray-500">
              No active statutory overrides recorded for the current scope.
            </div>
          ) : (
            <div className="overflow-x-auto">
              <table className="w-full text-xs text-left">
                <thead>
                  <tr className="border-b border-gray-200 text-gray-500 uppercase tracking-wider font-semibold">
                    <th className="pb-2">Check Name</th>
                    <th className="pb-2">Return Type</th>
                    <th className="pb-2">Overridden By</th>
                    <th className="pb-2">Justification / Reason</th>
                    <th className="pb-2">Timestamp</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-gray-100">
                  {recent_governance_overrides.map((ovr: any, idx: number) => (
                    <tr key={ovr.id || idx} className="hover:bg-gray-50/50">
                      <td className="py-2.5 font-semibold text-gray-900">{ovr.check_name || "Statutory Check"}</td>
                      <td className="py-2.5 font-mono text-gray-700">{ovr.return_type || "GSTR-3B"}</td>
                      <td className="py-2.5 text-gray-700">{ovr.partner_name || ovr.actor_id || "Partner"}</td>
                      <td className="py-2.5 text-gray-600 max-w-xs truncate">{ovr.reason || "Approved exception"}</td>
                      <td className="py-2.5 text-gray-400 font-mono">
                        {ovr.created_at ? new Date(ovr.created_at).toLocaleString() : "N/A"}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
